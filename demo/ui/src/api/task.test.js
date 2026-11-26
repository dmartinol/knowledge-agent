import { describe, expect, it } from 'vitest'

import {
  answerOf,
  artifactOf,
  clarificationOf,
  failureOf,
  isMessage,
  retrievedSources,
  splitAnswer,
  textOf,
  workflowOf,
} from './task.js'

const metadata = {
  loop: 'typed_tool',
  decision_source: 'llm',
  searches: 2,
  search_limit: 2,
  evidence_status: 'none',
  evidence: [],
  gaps: ['The search limit was reached.'],
  limitation: 'Unverified: no traceable references.',
  limits_hit: ['search'],
}

function completedTask(overrides = {}) {
  return {
    id: 'task-1',
    contextId: 'ctx-1',
    status: { state: 'completed' },
    artifacts: [
      {
        artifactId: 'artifact-1',
        name: 'knowledge-search-answer',
        parts: [{ kind: 'text', text: 'An answer.' }],
        metadata: { knowledge_agent: metadata },
      },
    ],
    ...overrides,
  }
}

describe('textOf', () => {
  it('joins text parts and skips other kinds', () => {
    expect(
      textOf([
        { kind: 'text', text: 'one' },
        { kind: 'file', file: {} },
        { kind: 'text', text: 'two' },
      ]),
    ).toBe('one\ntwo')
  })

  it('returns an empty string for missing parts', () => {
    expect(textOf(undefined)).toBe('')
  })
})

describe('task view model', () => {
  it('recognises a bare message reply', () => {
    expect(isMessage({ kind: 'message', parts: [] })).toBe(true)
    expect(isMessage(completedTask())).toBe(false)
  })

  it('reads the last artifact and its workflow metadata', () => {
    const task = completedTask({
      artifacts: [
        { parts: [{ kind: 'text', text: 'first' }], metadata: { knowledge_agent: { loop: 'old' } } },
        { parts: [{ kind: 'text', text: 'second' }], metadata: { knowledge_agent: metadata } },
      ],
    })

    expect(answerOf(task)).toBe('second')
    expect(workflowOf(task)).toBe(metadata)
    expect(artifactOf(task).parts[0].text).toBe('second')
  })

  it('falls back to the status message metadata', () => {
    const task = {
      status: { state: 'failed', message: { metadata: { knowledge_agent: { error: 'deadline' } } } },
    }

    expect(workflowOf(task)).toEqual({ error: 'deadline' })
  })

  it('returns clarification text only for input-required', () => {
    const pending = {
      status: { state: 'input-required', message: { parts: [{ kind: 'text', text: 'Which product?' }] } },
    }
    expect(clarificationOf(pending)).toBe('Which product?')
    expect(clarificationOf(completedTask())).toBeNull()
  })

  it('maps a failed task to a stable failure code', () => {
    const task = {
      status: {
        state: 'failed',
        message: { parts: [{ kind: 'text', text: 'The model timed out.' }] },
      },
      artifacts: [{ parts: [], metadata: { knowledge_agent: { error: 'model_timeout', limits_hit: ['tokens'] } } }],
    }

    expect(failureOf(task)).toEqual({
      code: 'model_timeout',
      message: 'The model timed out.',
      limitsHit: ['tokens'],
    })
    expect(failureOf(completedTask())).toBeNull()
  })

  it('maps a rejected task without workflow metadata', () => {
    const task = { status: { state: 'rejected', message: { parts: [{ kind: 'text', text: 'Busy.' }] } } }

    expect(failureOf(task)).toMatchObject({ code: 'rejected', limitsHit: [] })
  })
})

describe('splitAnswer', () => {
  it('separates the body, gaps, sources, and limitation', () => {
    const rendered = [
      'Routes expose a service.',
      '',
      'Gaps:',
      '- One gap',
      '- Another gap',
      'Sources:',
      '- Document A — https://example.test/a',
      '- Document B',
      'Limitation: Unverified: no traceable references.',
    ].join('\n')

    expect(splitAnswer(rendered)).toEqual({
      body: 'Routes expose a service.',
      gaps: ['One gap', 'Another gap'],
      sources: ['Document A — https://example.test/a', 'Document B'],
      limitation: 'Unverified: no traceable references.',
    })
  })

  it('returns empty values for empty text', () => {
    expect(splitAnswer('')).toEqual({ body: '', gaps: [], sources: [], limitation: null })
  })
})

describe('retrievedSources', () => {
  it('renders only retrieved references and keeps labels', () => {
    const sources = retrievedSources({
      evidence: [
        { title: 'Doc A', url: 'https://example.test/a', support: 'retrieved' },
        { title: 'Doc B', support: 'cited' },
        { document_id: 'doc-c', support: 'retrieved' },
      ],
    })

    expect(sources).toEqual([
      { label: 'Doc A', url: 'https://example.test/a', documentId: null, source: null },
      { label: 'doc-c', url: null, documentId: 'doc-c', source: null },
    ])
  })

  it('never counts cited or unknown support as a source', () => {
    expect(
      retrievedSources({ evidence: [{ title: 'A', support: 'cited' }, { title: 'B' }] }),
    ).toEqual([])
  })
})
