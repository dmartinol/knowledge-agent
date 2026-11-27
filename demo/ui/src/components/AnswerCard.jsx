import {
  Alert,
  Card,
  CardBody,
  Content,
  ContentVariants,
  Label,
} from '@patternfly/react-core'
import { retrievedSources, splitAnswer } from '../api/task.js'

function SourceList({ sources }) {
  return (
    <Content component={ContentVariants.ul} className="ka-sources">
      {sources.map((source, index) => (
        <Content
          component={ContentVariants.li}
          key={`${source.label}-${index}`}
        >
          {source.url ? (
            <a href={source.url} target="_blank" rel="noreferrer noopener">
              {source.label}
            </a>
          ) : (
            source.label
          )}
          {source.source && (
            <Label isCompact color="blue" className="ka-source-store">
              {source.source}
            </Label>
          )}
        </Content>
      ))}
    </Content>
  )
}

export default function AnswerCard({ text, metadata, state, elapsedMs }) {
  const parsed = splitAnswer(text)
  const gaps = Array.isArray(metadata?.gaps) ? metadata.gaps : parsed.gaps
  const limitation = metadata?.limitation ?? parsed.limitation ?? null
  const sources = metadata
    ? retrievedSources(metadata)
    : parsed.sources.map((label) => ({ label, url: null }))
  const searches = metadata?.searches
  const searchLimit = metadata?.search_limit
  const requests = metadata?.llm_requests
  const tokens = metadata?.llm_tokens

  return (
    <Card className="ka-answer" isPlain>
      <CardBody>
        {parsed.body && (
          <Content component={ContentVariants.p} className="ka-answer-body">
            {parsed.body}
          </Content>
        )}

        {gaps.length > 0 && (
          <div className="ka-block">
            <Content component={ContentVariants.h4}>Gaps</Content>
            <Content component={ContentVariants.ul}>
              {gaps.map((gap, index) => (
                <Content component={ContentVariants.li} key={index}>
                  {gap}
                </Content>
              ))}
            </Content>
          </div>
        )}

        {sources.length > 0 && (
          <div className="ka-block">
            <Content component={ContentVariants.h4}>Sources</Content>
            <SourceList sources={sources} />
          </div>
        )}

        {limitation && (
          <Alert
            variant="warning"
            isInline
            isPlain
            title={limitation}
            className="ka-unverified"
          />
        )}

        <div className="ka-answer-footer">
          <Label isCompact color={state === 'completed' ? 'green' : 'grey'}>
            {state ?? 'unknown'}
          </Label>
          {Number.isFinite(searches) && (
            <Label isCompact color="blue">
              {searches}/{searchLimit ?? '?'} searches
            </Label>
          )}
          {Number.isFinite(requests) && (
            <Label isCompact color="purple">
              {requests} requests
            </Label>
          )}
          {Number.isFinite(tokens) && (
            <Label isCompact color="teal" title="Total tokens reported by the provider">
              {tokens.toLocaleString()} tokens
            </Label>
          )}
          {Number.isFinite(elapsedMs) && elapsedMs > 0 && (
            <span className="ka-muted">{(elapsedMs / 1000).toFixed(1)}s</span>
          )}
        </div>
      </CardBody>
    </Card>
  )
}
