import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import ScenarioRail from './ScenarioRail.jsx'

describe('ScenarioRail', () => {
  it('prefills a scenario without sending it', async () => {
    const user = userEvent.setup()
    const onPickScenario = vi.fn()
    render(
      <ScenarioRail
        onPickScenario={onPickScenario}
        runs={[]}
        activeId={null}
        onSelectRun={() => {}}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Ambiguous request' }))

    expect(onPickScenario).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'ambiguous', prompt: 'Tell me about it.' }),
    )
    expect(screen.getByText('No runs yet.')).toBeInTheDocument()
  })

  it('restores a previous run', async () => {
    const user = userEvent.setup()
    const onSelectRun = vi.fn()
    const runs = [
      { id: 'run-1', question: 'How do Routes work?', state: 'completed', startedAt: Date.now(), verified: true },
      { id: 'run-2', question: 'Tell me about it.', state: 'input-required', startedAt: Date.now(), verified: false },
    ]
    render(
      <ScenarioRail
        onPickScenario={() => {}}
        runs={runs}
        activeId="run-2"
        onSelectRun={onSelectRun}
      />,
    )

    expect(screen.getByText('verified')).toBeInTheDocument()
    expect(screen.getByText('unverified')).toBeInTheDocument()
    await user.click(screen.getByText('How do Routes work?'))
    expect(onSelectRun).toHaveBeenCalledWith('run-1')
  })
})
