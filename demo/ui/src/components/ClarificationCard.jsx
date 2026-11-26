import { useState } from 'react'
import {
  Alert,
  Button,
  Card,
  CardBody,
  Content,
  ContentVariants,
  TextArea,
} from '@patternfly/react-core'

export default function ClarificationCard({ question, onSubmit, busy }) {
  const [value, setValue] = useState('')

  function submit() {
    const answer = value.trim()
    if (!answer || busy) return
    setValue('')
    onSubmit(answer)
  }

  return (
    <Card className="ka-clarification" isPlain>
      <CardBody>
        <Alert
          variant="info"
          isInline
          isPlain
          title="Awaiting your answer — one clarification per task"
        />
        <Content component={ContentVariants.p} className="ka-clarification-question">
          {question}
        </Content>
        <TextArea
          aria-label="Answer the clarification"
          value={value}
          onChange={(_event, next) => setValue(next)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
          resizeOrientation="vertical"
          rows={2}
        />
        <Button variant="primary" onClick={submit} isDisabled={busy || !value.trim()}>
          Answer
        </Button>
      </CardBody>
    </Card>
  )
}
