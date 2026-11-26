// A2A JSON-RPC transport plus the non-blocking send and polling loop.
// Every call is short so a Route idle timeout never sees the reasoning window.

export const TERMINAL_STATES = new Set([
  'completed',
  'failed',
  'rejected',
  'input-required',
])

export const FAILURE_STATES = new Set(['canceled', 'auth-required', 'auth_required'])

let sequence = 0

function nextId() {
  sequence += 1
  return `ui-${sequence}`
}

export async function rpc(method, params, { signal, onRaw } = {}) {
  const request = { jsonrpc: '2.0', id: nextId(), method, params }
  const response = await fetch('/a2a', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  if (!response.ok) {
    const error = new Error(`The agent answered HTTP ${response.status}.`)
    error.code = 'http_error'
    error.status = response.status
    if (onRaw) onRaw({ request, response: { httpStatus: response.status } })
    throw error
  }
  const payload = await response.json()
  if (onRaw) onRaw({ request, response: payload })
  if (payload.error) {
    const error = new Error(payload.error.message || 'The agent returned a JSON-RPC error.')
    error.code = 'jsonrpc_error'
    error.rpcCode = payload.error.code
    throw error
  }
  return payload.result
}

export function newMessage(text, { taskId, contextId } = {}) {
  const message = {
    kind: 'message',
    role: 'user',
    messageId: globalThis.crypto?.randomUUID?.() ?? `msg-${Date.now()}`,
    parts: [{ kind: 'text', text }],
  }
  if (taskId) message.taskId = taskId
  if (contextId) message.contextId = contextId
  return message
}

export function sendMessage(text, { taskId, contextId, signal, onRaw } = {}) {
  return rpc(
    'message/send',
    {
      message: newMessage(text, { taskId, contextId }),
      configuration: { blocking: false, acceptedOutputModes: ['text/plain'] },
    },
    { signal, onRaw },
  )
}

export function getTask(taskId, { signal, onRaw } = {}) {
  return rpc('tasks/get', { id: taskId }, { signal, onRaw })
}

export async function fetchCard({ signal } = {}) {
  const response = await fetch('/.well-known/agent-card.json', { signal })
  if (!response.ok) {
    const error = new Error(`The agent card request failed with HTTP ${response.status}.`)
    error.code = 'http_error'
    error.status = response.status
    throw error
  }
  return response.json()
}

export const defaultSleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function timeoutError() {
  const error = new Error('The agent did not finish in time.')
  error.code = 'ui_timeout'
  return error
}

// Bounds one poll: aborts the request and rejects when the slice runs out.
function pollDeadline(signal, ms) {
  const controller = new AbortController()
  const forward = () => controller.abort()
  if (signal?.aborted) controller.abort()
  else signal?.addEventListener('abort', forward, { once: true })
  let handle
  const promise = new Promise((resolve, reject) => {
    handle = setTimeout(() => {
      controller.abort()
      reject(timeoutError())
    }, ms)
  })
  return {
    signal: controller.signal,
    promise,
    cancel() {
      clearTimeout(handle)
      signal?.removeEventListener('abort', forward)
    },
  }
}

export async function waitForTask(taskId, options = {}) {
  const {
    getTaskFn = getTask,
    sleep = defaultSleep,
    now = () => Date.now(),
    intervalMs = 1000,
    slowIntervalMs = 2000,
    slowAfterMs = 20000,
    deadlineMs = 200000,
    onPoll,
    onRaw,
    signal,
  } = options
  const startedAt = now()
  for (;;) {
    const elapsed = now() - startedAt
    if (elapsed >= deadlineMs) throw timeoutError()
    const deadline = pollDeadline(signal, deadlineMs - elapsed)
    let task
    try {
      const request = Promise.resolve(getTaskFn(taskId, { signal: deadline.signal, onRaw }))
      // A poll that loses the race must not surface as an unhandled rejection.
      request.catch(() => {})
      task = await Promise.race([request, deadline.promise])
    } finally {
      deadline.cancel()
    }
    const state = task?.status?.state
    if (onPoll) onPoll(task, now() - startedAt)
    if (TERMINAL_STATES.has(state) || FAILURE_STATES.has(state)) return task
    await sleep(now() - startedAt >= slowAfterMs ? slowIntervalMs : intervalMs)
  }
}

export async function fetchHealth({ signal } = {}) {
  const response = await fetch('/a2a/health', { signal })
  if (!response.ok) {
    const error = new Error(`The health request failed with HTTP ${response.status}.`)
    error.code = 'http_error'
    error.status = response.status
    throw error
  }
  return response.json()
}
