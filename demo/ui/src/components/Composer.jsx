import {
  Button,
  Spinner,
  TextArea,
} from '@patternfly/react-core'

export default function Composer({ value, onChange, onSend, busy, disabledHint }) {
  function send() {
    const text = value.trim()
    if (!text || busy) return
    onSend(text)
  }

  return (
    <div className="ka-composer">
      <TextArea
        aria-label="Ask the knowledge agent"
        value={value}
        onChange={(_event, next) => onChange(next)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            send()
          }
        }}
        isDisabled={busy}
        placeholder={disabledHint || 'Ask a question. Enter sends, Shift+Enter adds a line.'}
        resizeOrientation="vertical"
        rows={3}
      />
      <Button variant="primary" onClick={send} isDisabled={busy || !value.trim()}>
        {busy ? (
          <>
            <Spinner size="sm" /> Working
          </>
        ) : (
          'Send'
        )}
      </Button>
    </div>
  )
}
