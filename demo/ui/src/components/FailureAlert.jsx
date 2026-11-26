import { Alert, Label } from '@patternfly/react-core'
import { describeError } from '../api/errors.js'

export default function FailureAlert({ code, message, limitsHit = [] }) {
  const copy = describeError(code)
  return (
    <Alert
      variant="danger"
      isInline
      title={copy.title}
      className="ka-failure"
      actionClose={null}
    >
      <p>{message || copy.detail}</p>
      <p className="ka-muted">{copy.detail}</p>
      <div className="ka-failure-meta">
        <Label isCompact color="red">
          {copy.code}
        </Label>
        {limitsHit.map((limit) => (
          <Label isCompact color="orange" key={limit}>
            limit: {limit}
          </Label>
        ))}
      </div>
    </Alert>
  )
}
