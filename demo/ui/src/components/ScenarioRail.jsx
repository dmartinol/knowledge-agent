import {
  Button,
  Content,
  ContentVariants,
  Divider,
  Label,
} from '@patternfly/react-core'
import { SCENARIOS } from '../api/scenarios.js'

const STATE_COLOR = {
  completed: 'green',
  failed: 'red',
  rejected: 'red',
  'input-required': 'blue',
  working: 'grey',
}

export default function ScenarioRail({ onPickScenario, runs, activeId, onSelectRun }) {
  return (
    <aside className="ka-rail">
      <Content component={ContentVariants.h3}>Demo scenarios</Content>
      <Content component={ContentVariants.small} className="ka-muted">
        Prefills the composer. Nothing is sent until you press Send.
      </Content>
      <ul className="ka-scenarios">
        {SCENARIOS.map((scenario) => (
          <li key={scenario.id}>
            <Button
              variant="link"
              isInline
              component="button"
              onClick={() => onPickScenario(scenario)}
              className="ka-scenario-button"
            >
              {scenario.label}
            </Button>
            <div className="ka-muted ka-scenario-hint">{scenario.hint}</div>
          </li>
        ))}
      </ul>

      <Divider />

      <Content component={ContentVariants.h3}>Runs</Content>
      {runs.length === 0 ? (
        <p className="ka-muted">No runs yet.</p>
      ) : (
        <ul className="ka-runs">
          {runs.map((run) => (
            <li key={run.id}>
              <Button
                variant={run.id === activeId ? 'secondary' : 'plain'}
                isBlock
                onClick={() => onSelectRun(run.id)}
                className="ka-run-button"
              >
                <span className="ka-run-line">
                  <Label isCompact color={STATE_COLOR[run.state] ?? 'grey'}>
                    {run.state ?? 'idle'}
                  </Label>
                  {run.verified ? (
                    <Label isCompact color="green">
                      verified
                    </Label>
                  ) : (
                    <Label isCompact color="orange">
                      unverified
                    </Label>
                  )}
                </span>
                <span className="ka-run-question">{run.question}</span>
                <span className="ka-muted ka-run-time">
                  {new Date(run.startedAt).toLocaleTimeString()}
                </span>
              </Button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
