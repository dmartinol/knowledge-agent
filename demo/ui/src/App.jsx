import { Component, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Content,
  ContentVariants,
  Label,
  Masthead,
  MastheadBrand,
  MastheadContent,
  MastheadMain,
  Spinner,
  Title,
} from '@patternfly/react-core'
import {
  FAILURE_STATES,
  TERMINAL_STATES,
  defaultSleep,
  fetchCard,
  fetchHealth,
  sendMessage,
  waitForTask,
} from './api/client.js'
import {
  answerOf,
  clarificationOf,
  failureOf,
  isMessage,
  textOf,
  workflowOf,
} from './api/task.js'
import AnswerCard from './components/AnswerCard.jsx'
import ClarificationCard from './components/ClarificationCard.jsx'
import Composer from './components/Composer.jsx'
import FailureAlert from './components/FailureAlert.jsx'
import Inspector from './components/Inspector.jsx'
import ScenarioRail from './components/ScenarioRail.jsx'

const DEFAULT_CLIENT = { fetchCard, fetchHealth, sendMessage, waitForTask }
const RUN_POLL_OPTIONS = { sleep: defaultSleep }

function settled(task) {
  const state = task?.status?.state
  return TERMINAL_STATES.has(state) || FAILURE_STATES.has(state)
}

export function isVerified(metadata) {
  const evidence = Array.isArray(metadata?.evidence) ? metadata.evidence : []
  return evidence.some((entry) => entry?.support === 'retrieved')
}

function newRun(question) {
  return {
    id: `run-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    question,
    taskId: null,
    contextId: null,
    state: 'working',
    turns: [{ id: 'turn-0', role: 'user', text: question }],
    answer: null,
    metadata: null,
    failure: null,
    raw: [],
    startedAt: Date.now(),
    elapsedMs: 0,
    verified: false,
  }
}

class RunBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error) {
    console.error('Console render failed', error)
  }

  render() {
    if (this.state.error) {
      return (
        <Alert variant="danger" isInline title="The console hit an unexpected error">
          {String(this.state.error?.message ?? this.state.error)}
        </Alert>
      )
    }
    return this.props.children
  }
}

export default function App({ client = DEFAULT_CLIENT }) {
  const [card, setCard] = useState(null)
  const [health, setHealth] = useState('connecting')
  const [cardError, setCardError] = useState(null)
  const [input, setInput] = useState('')
  const [runs, setRuns] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [busy, setBusy] = useState(false)
  const [announcement, setAnnouncement] = useState('')
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [railOpen, setRailOpen] = useState(false)
  const bottomRef = useRef(null)
  const pinnedRef = useRef(true)

  const active = useMemo(
    () => runs.find((run) => run.id === activeId) ?? runs[0] ?? null,
    [runs, activeId],
  )

  useEffect(() => {
    let cancelled = false
    client
      .fetchCard()
      .then((payload) => {
        if (!cancelled) setCard(payload)
      })
      .catch((error) => {
        if (!cancelled) setCardError(error.message)
      })
    client
      .fetchHealth()
      .then((payload) => {
        if (!cancelled) setHealth(payload?.status ?? 'unknown')
      })
      .catch(() => {
        if (!cancelled) setHealth('unreachable')
      })
    return () => {
      cancelled = true
    }
  }, [client])

  useEffect(() => {
    if (!pinnedRef.current || !bottomRef.current) return
    bottomRef.current.scrollIntoView?.({ block: 'end' })
  }, [active?.turns?.length, active?.state])

  const updateRun = useCallback((runId, patch) => {
    setRuns((current) =>
      current.map((run) => (run.id === runId ? { ...run, ...patch } : run)),
    )
  }, [])

  const applyTask = useCallback(
    (runId, task, elapsedMs, raw) => {
      const state = task?.status?.state ?? 'unknown'
      const metadata = workflowOf(task) ?? null
      const answer = answerOf(task)
      const clarification = clarificationOf(task)
      const failure = failureOf(task)
      const turnId = `turn-${Date.now()}`
      let nextTurn = null
      if (answer) {
        nextTurn = {
          id: turnId,
          role: 'agent',
          kind: 'answer',
          text: answer,
          metadata,
          state,
          elapsedMs,
        }
      } else if (clarification) {
        nextTurn = {
          id: turnId,
          role: 'agent',
          kind: 'clarification',
          text: clarification,
          state,
        }
      } else if (failure) {
        nextTurn = {
          id: turnId,
          role: 'agent',
          kind: 'failure',
          failure,
          state,
        }
      }
      setRuns((current) =>
        current.map((run) =>
          run.id === runId
            ? {
                ...run,
                taskId: task?.id ?? run.taskId,
                contextId: task?.contextId ?? run.contextId,
                state,
                answer: answer ?? run.answer,
                metadata: metadata ?? run.metadata,
                failure: failure ?? run.failure,
                verified: isVerified(metadata ?? run.metadata),
                elapsedMs,
                raw: raw.length > 0 ? [...raw] : run.raw,
                turns: nextTurn ? [...run.turns, nextTurn] : run.turns,
              }
            : run,
        ),
      )
      if (state === 'completed') {
        setAnnouncement('Run completed.')
      } else if (state === 'input-required') {
        setAnnouncement('The agent needs one clarification before continuing.')
      } else if (failure) {
        setAnnouncement(`Run failed: ${failure.code}.`)
      }
    },
    [],
  )

  const applyError = useCallback(
    (runId, error, raw) => {
      const code = error?.code ?? 'unknown'
      const turn = {
        id: `turn-${Date.now()}`,
        role: 'agent',
        kind: 'failure',
        failure: { code, message: error?.message ?? '', limitsHit: [] },
        state: 'failed',
      }
      setRuns((current) =>
        current.map((run) =>
          run.id === runId
            ? {
                ...run,
                state: 'failed',
                failure: turn.failure,
                verified: false,
                raw: raw.length > 0 ? [...raw] : run.raw,
                turns: [...run.turns, turn],
              }
            : run,
        ),
      )
      setAnnouncement(`Run failed: ${code}.`)
    },
    [],
  )

  const runExchange = useCallback(
    async (runId, text, { taskId = null, contextId = null } = {}) => {
      setBusy(true)
      pinnedRef.current = true
      setAnnouncement('Request sent. The agent is working.')
      const startedAt = Date.now()
      const raw = []
      const onRaw = (entry) => {
        raw.push(entry)
      }
      try {
        const first = await client.sendMessage(text, { taskId, contextId, onRaw })
        if (isMessage(first)) {
          const reply = textOf(first.parts)
          const metadata = first.metadata?.knowledge_agent ?? null
          setRuns((current) =>
            current.map((run) =>
              run.id === runId
                ? {
                    ...run,
                    state: 'completed',
                    answer: reply,
                    metadata,
                    verified: isVerified(metadata),
                    elapsedMs: Date.now() - startedAt,
                    raw: [...raw],
                    turns: [
                      ...run.turns,
                      {
                        id: `turn-${Date.now()}`,
                        role: 'agent',
                        kind: 'answer',
                        text: reply,
                        metadata,
                        state: 'completed',
                        elapsedMs: Date.now() - startedAt,
                      },
                    ],
                  }
                : run,
            ),
          )
          setAnnouncement('Run completed.')
          return
        }
        const nextTaskId = first?.id ?? taskId
        const nextContextId = first?.contextId ?? contextId
        updateRun(runId, {
          taskId: nextTaskId,
          contextId: nextContextId,
          state: first?.status?.state ?? 'working',
          raw: [...raw],
        })
        const task = settled(first)
          ? first
          : await client.waitForTask(nextTaskId, {
              ...RUN_POLL_OPTIONS,
              onRaw,
              onPoll: (snapshot, elapsedMs) =>
                updateRun(runId, {
                  taskId: snapshot?.id ?? nextTaskId,
                  contextId: snapshot?.contextId ?? nextContextId,
                  state: snapshot?.status?.state ?? 'working',
                  elapsedMs,
                  raw: [...raw],
                }),
            })
        applyTask(runId, task, Date.now() - startedAt, raw)
      } catch (error) {
        applyError(runId, error, raw)
      } finally {
        setBusy(false)
      }
    },
    [applyError, applyTask, client, updateRun],
  )

  const onSend = useCallback(
    (text) => {
      const run = newRun(text)
      setRuns((current) => [run, ...current])
      setActiveId(run.id)
      setInput('')
      void runExchange(run.id, text)
    },
    [runExchange],
  )

  const onClarify = useCallback(
    (text) => {
      if (!active) return
      const turn = {
        id: `turn-${Date.now()}`,
        role: 'user',
        text,
      }
      setRuns((current) =>
        current.map((run) =>
          run.id === active.id
            ? { ...run, turns: [...run.turns, turn], state: 'working' }
            : run,
        ),
      )
      void runExchange(active.id, text, {
        taskId: active.taskId,
        contextId: active.contextId,
      })
    },
    [active, runExchange],
  )

  const onPickScenario = useCallback((scenario) => {
    setInput(scenario.prompt)
    setRailOpen(false)
  }, [])

  const onSelectRun = useCallback((runId) => {
    setActiveId(runId)
    setRailOpen(false)
  }, [])

  const startNewRun = useCallback(() => {
    setActiveId(null)
    setInput('')
    setAnnouncement('Ready for a new question.')
  }, [])

  const awaitingClarification = active?.state === 'input-required'
  const waiting = active?.state === 'working' || active?.state === 'submitted'

  const masthead = (
    <Masthead>
      <MastheadMain>
        <MastheadBrand>
          <span className="ka-brand">Knowledge Search Agent</span>
        </MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <div className="ka-masthead-status">
          <Label
            isCompact
            color={health === 'healthy' ? 'green' : health === 'connecting' ? 'grey' : 'red'}
          >
            {health}
          </Label>
          {card ? (
            <span className="ka-muted ka-card-id">
              {card.name} v{card.version} · protocol {card.protocolVersion}
            </span>
          ) : (
            <span className="ka-muted">{cardError ?? 'Agent Card loading…'}</span>
          )}
          <div className="ka-masthead-actions">
            <Button
              variant="plain"
              className="ka-drawer-toggle"
              aria-expanded={railOpen}
              onClick={() => setRailOpen((open) => !open)}
            >
              Scenarios
            </Button>
            <Button
              variant="plain"
              className="ka-drawer-toggle"
              aria-expanded={inspectorOpen}
              onClick={() => setInspectorOpen((open) => !open)}
            >
              Inspector
            </Button>
          </div>
        </div>
      </MastheadContent>
    </Masthead>
  )

  return (
    <RunBoundary>
      <div className="ka-shell">
        {masthead}
        <div className="ka-grid">
          <div className={`ka-rail-slot${railOpen ? ' ka-drawer-open' : ''}`}>
            <ScenarioRail
              onPickScenario={onPickScenario}
              runs={runs}
              activeId={active?.id ?? null}
              onSelectRun={onSelectRun}
            />
          </div>

          <main className="ka-main">
            <div
              className="ka-transcript"
              role="log"
              aria-label="Conversation"
              onScroll={(event) => {
                const target = event.currentTarget
                pinnedRef.current =
                  target.scrollHeight - target.scrollTop - target.clientHeight < 80
              }}
            >
              {!active && (
                <div className="ka-empty">
                  <Title headingLevel="h1" size="2xl">
                    Ask a question, watch the reasoning
                  </Title>
                  <Content component={ContentVariants.p} className="ka-muted">
                    Pick a scenario on the left to prefill the composer. The right
                    panel exposes workflow state, structured evidence, and the raw
                    A2A exchange.
                  </Content>
                  <Alert
                    variant="info"
                    isInline
                    isPlain
                    title="This console is not a chat product"
                    className="ka-empty-note"
                  >
                    One task runs at a time. Clarification is offered once per task,
                    and cancellation is not implemented by the agent.
                  </Alert>
                </div>
              )}

              {active?.turns.map((turn) => {
                if (turn.role === 'user') {
                  return (
                    <div className="ka-bubble ka-bubble-user" key={turn.id}>
                      <span className="ka-bubble-role">You</span>
                      <Content component={ContentVariants.p}>{turn.text}</Content>
                    </div>
                  )
                }
                if (turn.kind === 'answer') {
                  return (
                    <AnswerCard
                      key={turn.id}
                      text={turn.text}
                      metadata={turn.metadata}
                      state={turn.state}
                      elapsedMs={turn.elapsedMs}
                    />
                  )
                }
                if (turn.kind === 'clarification') {
                  const latest = turn.id === active.turns[active.turns.length - 1]?.id
                  return (
                    <ClarificationCard
                      key={turn.id}
                      question={turn.text}
                      onSubmit={onClarify}
                      busy={busy || !latest}
                    />
                  )
                }
                if (turn.kind === 'failure') {
                  return (
                    <FailureAlert
                      key={turn.id}
                      code={turn.failure?.code}
                      message={turn.failure?.message}
                      limitsHit={turn.failure?.limitsHit}
                    />
                  )
                }
                return null
              })}

              {active && waiting && (
                <div className="ka-working" aria-live="polite">
                  <Spinner size="md" aria-label="The agent is working" />
                  <span>
                    {active.state === 'submitted' ? 'Queued' : 'Reasoning'} ·{' '}
                    {(active.elapsedMs / 1000).toFixed(1)}s
                  </span>
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            <div className="ka-composer-bar">
              <div className="ka-composer-meta">
                <span className="ka-muted">
                  {awaitingClarification
                    ? 'Answer the clarification to resume the same task.'
                    : 'Enter sends · Shift+Enter adds a line'}
                </span>
                <Button variant="link" isInline onClick={startNewRun}>
                  Start new run
                </Button>
              </div>
              <Composer
                value={input}
                onChange={setInput}
                onSend={onSend}
                busy={busy || awaitingClarification}
                disabledHint={
                  awaitingClarification
                    ? 'Answer the clarification above first.'
                    : undefined
                }
              />
            </div>
          </main>

          <div className={`ka-inspector-slot${inspectorOpen ? ' ka-drawer-open' : ''}`}>
            <aside className="ka-inspector-pane">
              <Inspector
                task={{ id: active?.taskId, contextId: active?.contextId }}
                metadata={active?.metadata}
                raw={active?.raw ?? []}
                card={card}
              />
            </aside>
          </div>
        </div>

        {(railOpen || inspectorOpen) && (
          <button
            type="button"
            className="ka-backdrop"
            aria-label="Close panel"
            onClick={() => {
              setRailOpen(false)
              setInspectorOpen(false)
            }}
          />
        )}
        <div className="ka-sr-only" aria-live="polite">
          {announcement}
        </div>
      </div>
    </RunBoundary>
  )
}
