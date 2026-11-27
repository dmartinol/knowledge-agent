import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import AnswerCard from './AnswerCard.jsx'

describe('AnswerCard', () => {
  it('renders retrieved evidence as Sources and shows the workflow footer', () => {
    render(
      <AnswerCard
        text={'Routes expose a Service through a hostname.'}
        metadata={{
          evidence: [
            {
              title: 'Doc A',
              url: 'https://example.test/a',
              source: 'okp',
              support: 'retrieved',
            },
          ],
          gaps: ['The search limit was reached.'],
          limitation: null,
          searches: 2,
          search_limit: 2,
          llm_requests: 3,
          llm_tokens: 1200,
        }}
        state="completed"
        elapsedMs={4200}
      />,
    )

    expect(screen.getByText('Gaps')).toBeInTheDocument()
    expect(screen.getByText('The search limit was reached.')).toBeInTheDocument()
    expect(screen.getByText('Sources')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Doc A' })).toHaveAttribute(
      'href',
      'https://example.test/a',
    )
    expect(screen.getByText('okp')).toBeInTheDocument()
    expect(screen.queryByText(/Unverified/)).not.toBeInTheDocument()
    expect(screen.getByText('2/2 searches')).toBeInTheDocument()
    expect(screen.getByText('3 requests')).toBeInTheDocument()
    expect(screen.getByText('1,200 tokens')).toBeInTheDocument()
    expect(screen.getByText('4.2s')).toBeInTheDocument()
    expect(screen.getByText('completed')).toBeInTheDocument()
  })

  it('never renders cited references as Sources and shows the unverified banner', () => {
    render(
      <AnswerCard
        text="A synthesised answer."
        metadata={{
          evidence: [{ title: 'Doc B', support: 'cited' }],
          gaps: [],
          limitation: 'Unverified: the knowledge service returned no traceable references.',
        }}
        state="completed"
      />,
    )

    expect(screen.queryByText('Sources')).not.toBeInTheDocument()
    expect(screen.queryByText('Doc B')).not.toBeInTheDocument()
    expect(screen.getByText(/Unverified/)).toBeInTheDocument()
  })

  it('falls back to the rendered text when metadata is absent', () => {
    render(
      <AnswerCard
        text={[
          'Routes have three TLS modes.',
          '',
          'Sources:',
          '- Document A — https://example.test/a',
          'Limitation: Unverified: no traceable references.',
        ].join('\n')}
        state="completed"
      />,
    )

    expect(screen.getByText('Document A — https://example.test/a')).toBeInTheDocument()
    expect(screen.getByText(/Unverified/)).toBeInTheDocument()
  })
})
