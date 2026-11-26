import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import Inspector from './Inspector.jsx'

const metadata = {
  loop: 'typed_tool',
  decision_source: 'llm',
  searches: 1,
  search_limit: 2,
  evidence_status: 'available',
  evidence: [
    {
      search: 0,
      source: 'okp',
      document_id: 'doc-1',
      title: 'OpenShift Routes',
      url: 'https://example.test/routes',
      support: 'retrieved',
    },
    { search: 1, title: 'Unverified note', support: 'cited' },
  ],
  gaps: [],
  limitation: null,
  llm_requests: 2,
  llm_tokens: 900,
  clarification_used: false,
  limits_hit: [],
}

const raw = [
  {
    request: { jsonrpc: '2.0', method: 'message/send', params: { message: { parts: [] } } },
    response: { jsonrpc: '2.0', result: { id: 'task-1' } },
  },
]

describe('Inspector', () => {
  it('shows workflow state, evidence support, and the raw exchange', async () => {
    const user = userEvent.setup()
    render(
      <Inspector
        task={{ id: 'task-1', contextId: 'ctx-1' }}
        metadata={metadata}
        raw={raw}
        card={{ name: 'Knowledge Search Agent', version: '0.1.0' }}
      />,
    )

    expect(screen.getByText('typed_tool')).toBeInTheDocument()
    expect(screen.getByText('llm')).toBeInTheDocument()
    expect(screen.getByText('1 / 2')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: /Evidence/ }))
    expect(screen.getByText('retrieved')).toBeInTheDocument()
    expect(screen.getByText('cited')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'OpenShift Routes' })).toBeInTheDocument()
    expect(screen.getByText('doc-1')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: /Raw/ }))
    expect(document.body.textContent).toContain('message/send')
    expect(document.body.textContent).toContain('task-1')
    expect(document.body.textContent).toContain('Knowledge Search Agent')
  })

  it('explains when no workflow metadata exists yet', () => {
    render(<Inspector task={{}} metadata={null} raw={[]} card={null} />)

    expect(screen.getByText('No workflow metadata yet.')).toBeInTheDocument()
  })
})
