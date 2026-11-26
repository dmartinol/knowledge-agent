import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import App from './App.jsx'

function task(state, extra = {}) {
  return { id: 'task-1', contextId: 'ctx-1', status: { state }, ...extra }
}

const completedTask = task('completed', {
  artifacts: [
    {
      name: 'knowledge-search-answer',
      parts: [{ kind: 'text', text: 'Routes expose a Service on a generated hostname.' }],
      metadata: {
        knowledge_agent: {
          loop: 'typed_tool',
          decision_source: 'llm',
          searches: 1,
          search_limit: 2,
          evidence_status: 'unavailable',
          evidence: [],
          gaps: [],
          limitation: 'Unverified: the knowledge service returned no traceable references.',
          llm_requests: 2,
          llm_tokens: 640,
          clarification_used: true,
          limits_hit: [],
        },
      },
    },
  ],
})

const pendingClarification = task('input-required', {
  status: {
    state: 'input-required',
    message: { parts: [{ kind: 'text', text: 'Which product do you mean?' }] },
  },
})

function fakeClient(overrides = {}) {
  return {
    fetchCard: vi.fn(async () => ({
      name: 'Knowledge Search Agent',
      version: '0.1.0',
      protocolVersion: '0.3.0',
    })),
    fetchHealth: vi.fn(async () => ({ status: 'healthy' })),
    sendMessage: vi.fn(async () => task('submitted')),
    waitForTask: vi.fn(),
    ...overrides,
  }
}

describe('App', () => {
  it('keeps the panel toggles wired to their panes', async () => {
    const user = userEvent.setup()
    render(<App client={fakeClient()} />)

    const inspector = screen.getByRole('button', { name: 'Inspector' })
    expect(inspector).toHaveAttribute('aria-controls', 'ka-inspector-slot')
    expect(inspector).toHaveAttribute('aria-expanded', 'false')

    await user.click(inspector)

    expect(inspector).toHaveAttribute('aria-expanded', 'true')
    expect(document.getElementById('ka-inspector-slot')).toHaveClass('ka-drawer-open')
    expect(screen.getByRole('button', { name: 'Close panel' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Close panel' }))

    expect(inspector).toHaveAttribute('aria-expanded', 'false')
  })

  it('lets a new run start while an older one awaits clarification', async () => {
    const user = userEvent.setup()
    const client = fakeClient({
      waitForTask: vi
        .fn()
        .mockResolvedValueOnce(pendingClarification)
        .mockResolvedValueOnce(completedTask),
    })
    render(<App client={client} />)

    await user.type(screen.getByLabelText('Ask the knowledge agent'), 'Tell me about it.{Enter}')
    expect(await screen.findByText('Which product do you mean?')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Start new run' }))

    const composer = screen.getByLabelText('Ask the knowledge agent')
    expect(composer).toBeEnabled()
    await user.type(composer, 'What is a Route?{Enter}')

    expect(
      await screen.findByText('Routes expose a Service on a generated hostname.'),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Ask the knowledge agent')).toBeEnabled()
  })

  it('runs a clarification and resumes the same task', async () => {
    const user = userEvent.setup()
    const client = fakeClient({
      waitForTask: vi
        .fn()
        .mockResolvedValueOnce(pendingClarification)
        .mockResolvedValueOnce(completedTask),
    })
    render(<App client={client} />)

    expect(await screen.findByText(/Knowledge Search Agent v0.1.0/)).toBeInTheDocument()
    expect(await screen.findByText('healthy')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Ask the knowledge agent'), 'Tell me about it.{Enter}')
    expect(await screen.findByText('Which product do you mean?')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Answer the clarification'), 'OpenShift Route{Enter}')

    expect(
      await screen.findByText('Routes expose a Service on a generated hostname.'),
    ).toBeInTheDocument()
    expect(screen.getByText(/Unverified/)).toBeInTheDocument()

    expect(client.sendMessage).toHaveBeenCalledTimes(2)
    expect(client.sendMessage.mock.calls[0][0]).toBe('Tell me about it.')
    expect(client.sendMessage.mock.calls[1][0]).toBe('OpenShift Route')
    expect(client.sendMessage.mock.calls[1][1]).toMatchObject({
      taskId: 'task-1',
      contextId: 'ctx-1',
    })
    expect(client.waitForTask).toHaveBeenCalledTimes(2)

    await waitFor(() => {
      expect(screen.getAllByText('completed').length).toBeGreaterThan(0)
    })
  })

  it('shows a stable failure code when the run fails', async () => {
    const user = userEvent.setup()
    const client = fakeClient({
      waitForTask: vi.fn().mockResolvedValue(
        task('failed', {
          status: {
            state: 'failed',
            message: { parts: [{ kind: 'text', text: 'The model timed out.' }] },
          },
          artifacts: [
            {
              parts: [],
              metadata: { knowledge_agent: { error: 'model_timeout', limits_hit: [] } },
            },
          ],
        }),
      ),
    })
    render(<App client={client} />)

    await user.type(screen.getByLabelText('Ask the knowledge agent'), 'Question{Enter}')

    expect(await screen.findByText('The reasoning model timed out')).toBeInTheDocument()
    expect(screen.getAllByText('model_timeout').length).toBeGreaterThan(0)
    expect(screen.getByText('The model timed out.')).toBeInTheDocument()
  })

  it('keeps each run in the rail and restores it on selection', async () => {
    const user = userEvent.setup()
    const client = fakeClient({ waitForTask: vi.fn().mockResolvedValue(completedTask) })
    render(<App client={client} />)

    await user.type(screen.getByLabelText('Ask the knowledge agent'), 'First question{Enter}')
    await screen.findByText('Routes expose a Service on a generated hostname.')
    await user.type(screen.getByLabelText('Ask the knowledge agent'), 'Second question{Enter}')

    const runs = await screen.findAllByRole('button', { name: /question/ })
    expect(runs.length).toBeGreaterThanOrEqual(2)

    await user.click(screen.getByRole('button', { name: /First question/ }))
    expect(within(screen.getByRole('log')).getByText('First question')).toBeInTheDocument()
  })
})
