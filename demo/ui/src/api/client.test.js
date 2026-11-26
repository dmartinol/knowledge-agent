import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  fetchCard,
  getTask,
  sendMessage,
  waitForTask,
} from './client.js'

function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  }
}

function stubFetch(handler) {
  const fetchMock = vi.fn(handler)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastBody(fetchMock) {
  return JSON.parse(fetchMock.mock.calls.at(-1)[1].body)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('sendMessage', () => {
  it('sends a non-blocking message/send with one text part', async () => {
    const fetchMock = stubFetch(async () => jsonResponse({
      jsonrpc: '2.0',
      id: 'ui-1',
      result: { id: 'task-1', status: { state: 'submitted' } },
    }))

    const result = await sendMessage('How do Routes work?')

    expect(result.id).toBe('task-1')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/a2a')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })

    const body = lastBody(fetchMock)
    expect(body).toMatchObject({
      jsonrpc: '2.0',
      method: 'message/send',
      params: { configuration: { blocking: false, acceptedOutputModes: ['text/plain'] } },
    })
    expect(body.params.message).toMatchObject({
      kind: 'message',
      role: 'user',
      parts: [{ kind: 'text', text: 'How do Routes work?' }],
    })
    expect(typeof body.params.message.messageId).toBe('string')
    expect(body.params.message.messageId.length).toBeGreaterThan(8)
    expect(body.params.message).not.toHaveProperty('taskId')
    expect(body.params.message).not.toHaveProperty('contextId')
  })

  it('reuses taskId and contextId when resuming a clarification', async () => {
    const fetchMock = stubFetch(async () => jsonResponse({
      jsonrpc: '2.0',
      id: 'ui-2',
      result: { id: 'task-9', status: { state: 'working' } },
    }))

    await sendMessage('The OpenShift Route API.', { taskId: 'task-9', contextId: 'ctx-9' })

    const message = lastBody(fetchMock).params.message
    expect(message.taskId).toBe('task-9')
    expect(message.contextId).toBe('ctx-9')
  })

  it('records the raw exchange when a callback is supplied', async () => {
    const payload = {
      jsonrpc: '2.0',
      id: 'ui-3',
      result: { id: 'task-1', status: { state: 'submitted' } },
    }
    stubFetch(async () => jsonResponse(payload))
    const onRaw = vi.fn()

    await sendMessage('question', { onRaw })

    expect(onRaw).toHaveBeenCalledWith(
      expect.objectContaining({ request: expect.objectContaining({ method: 'message/send' }), response: payload }),
    )
  })

  it('maps an HTTP failure to http_error', async () => {
    stubFetch(async () => jsonResponse({ detail: 'nope' }, 503))

    await expect(sendMessage('question')).rejects.toMatchObject({
      code: 'http_error',
      status: 503,
    })
  })

  it('maps a JSON-RPC error to jsonrpc_error', async () => {
    stubFetch(async () => jsonResponse({
      jsonrpc: '2.0',
      id: 'ui-4',
      error: { code: -32602, message: 'Invalid params' },
    }))

    await expect(sendMessage('question')).rejects.toMatchObject({
      code: 'jsonrpc_error',
      rpcCode: -32602,
      message: 'Invalid params',
    })
  })
})

describe('getTask', () => {
  it('posts tasks/get with the task id', async () => {
    const fetchMock = stubFetch(async () => jsonResponse({
      jsonrpc: '2.0',
      id: 'ui-5',
      result: { id: 'task-1', status: { state: 'working' } },
    }))

    await getTask('task-1')

    expect(lastBody(fetchMock)).toMatchObject({
      method: 'tasks/get',
      params: { id: 'task-1' },
    })
  })
})

describe('waitForTask', () => {
  function clockedSleep() {
    const clock = { t: 0 }
    const sleep = vi.fn(async (ms) => {
      clock.t += ms
    })
    return { clock, sleep, now: () => clock.t }
  }

  it.each(['completed', 'failed', 'rejected', 'input-required'])(
    'stops on the terminal state %s',
    async (state) => {
      const getTaskFn = vi.fn(async () => ({ id: 'task-1', status: { state } }))
      const { sleep, now } = clockedSleep()

      const task = await waitForTask('task-1', { getTaskFn, sleep, now })

      expect(task.status.state).toBe(state)
      expect(sleep).not.toHaveBeenCalled()
    },
  )

  it.each(['canceled', 'auth-required', 'auth_required'])(
    'stops on the failure state %s',
    async (state) => {
      const getTaskFn = vi.fn(async () => ({ id: 'task-1', status: { state } }))
      const { sleep, now } = clockedSleep()

      const task = await waitForTask('task-1', { getTaskFn, sleep, now })

      expect(task.status.state).toBe(state)
    },
  )

  it('polls every second, backs off to two seconds, and reports progress', async () => {
    const { clock, sleep, now } = clockedSleep()
    const getTaskFn = vi.fn(async () => {
      clock.t += 0
      return {
        id: 'task-1',
        status: { state: clock.t >= 25000 ? 'completed' : 'working' },
      }
    })
    const onPoll = vi.fn()

    await waitForTask('task-1', { getTaskFn, sleep, now, onPoll })

    const intervals = sleep.mock.calls.map(([ms]) => ms)
    expect(intervals.slice(0, 3)).toEqual([1000, 1000, 1000])
    expect(intervals).toContain(2000)
    expect(onPoll).toHaveBeenCalled()
  })

  it('gives up at its own deadline with ui_timeout', async () => {
    const { sleep, now } = clockedSleep()
    const getTaskFn = vi.fn(async () => ({ id: 'task-1', status: { state: 'working' } }))

    await expect(waitForTask('task-1', { getTaskFn, sleep, now })).rejects.toMatchObject({
      code: 'ui_timeout',
    })
    expect(now()).toBeGreaterThanOrEqual(200000)
  })

  it('gives up when a poll request never settles', async () => {
    const getTaskFn = vi.fn(() => new Promise(() => {}))

    await expect(
      waitForTask('task-1', { getTaskFn, deadlineMs: 25 }),
    ).rejects.toMatchObject({ code: 'ui_timeout' })
  })

  it('honours an injected deadline', async () => {
    const { sleep, now } = clockedSleep()
    const getTaskFn = vi.fn(async () => ({ id: 'task-1', status: { state: 'working' } }))

    await expect(
      waitForTask('task-1', { getTaskFn, sleep, now, deadlineMs: 3000 }),
    ).rejects.toMatchObject({ code: 'ui_timeout' })
    expect(sleep).toHaveBeenCalledTimes(3)
  })
})

describe('fetchCard', () => {
  it('reads the well-known agent card', async () => {
    const fetchMock = stubFetch(async () => jsonResponse({ name: 'Knowledge Search Agent' }))

    const card = await fetchCard()

    expect(card.name).toBe('Knowledge Search Agent')
    expect(fetchMock.mock.calls[0][0]).toBe('/.well-known/agent-card.json')
  })
})
