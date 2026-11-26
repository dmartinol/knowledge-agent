import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import ClarificationCard from './ClarificationCard.jsx'

describe('ClarificationCard', () => {
  it('submits the typed answer once', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(
      <ClarificationCard question="Which product do you mean?" onSubmit={onSubmit} busy={false} />,
    )

    expect(screen.getByText('Which product do you mean?')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Answer the clarification'), 'OpenShift Container Platform')
    await user.click(screen.getByRole('button', { name: 'Answer' }))

    expect(onSubmit).toHaveBeenCalledWith('OpenShift Container Platform')
  })

  it('disables submission while busy and for empty input', () => {
    const { rerender } = render(
      <ClarificationCard question="Which product?" onSubmit={() => {}} busy={false} />,
    )
    expect(screen.getByRole('button', { name: 'Answer' })).toBeDisabled()

    rerender(<ClarificationCard question="Which product?" onSubmit={() => {}} busy />)
    expect(screen.getByRole('button', { name: 'Answer' })).toBeDisabled()
  })
})
