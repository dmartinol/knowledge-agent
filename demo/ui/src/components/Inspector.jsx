import { useMemo, useState } from 'react'
import {
  ClipboardCopy,
  CodeBlock,
  CodeBlockCode,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Label,
  Tab,
  TabTitleText,
  Tabs,
} from '@patternfly/react-core'
import { Table, Tbody, Td, Th, Thead, Tr } from '@patternfly/react-table'
import { sourceLabel } from '../api/task.js'

function supportLabel(support) {
  if (support === 'retrieved') return <Label isCompact color="green">retrieved</Label>
  if (support === 'cited') return <Label isCompact color="grey">cited</Label>
  return <Label isCompact color="grey">unknown</Label>
}

function Workflow({ metadata, task }) {
  if (!metadata) {
    return <p className="ka-muted">No workflow metadata yet.</p>
  }
  const limits = Array.isArray(metadata.limits_hit) ? metadata.limits_hit : []
  return (
    <DescriptionList isCompact className="ka-workflow">
      <DescriptionListGroup>
        <DescriptionListTerm>loop</DescriptionListTerm>
        <DescriptionListDescription>{metadata.loop ?? '—'}</DescriptionListDescription>
      </DescriptionListGroup>
      <DescriptionListGroup>
        <DescriptionListTerm>decision source</DescriptionListTerm>
        <DescriptionListDescription>{metadata.decision_source ?? '—'}</DescriptionListDescription>
      </DescriptionListGroup>
      <DescriptionListGroup>
        <DescriptionListTerm>retriever</DescriptionListTerm>
        <DescriptionListDescription>{metadata.retriever ?? '—'}</DescriptionListDescription>
      </DescriptionListGroup>
      <DescriptionListGroup>
        <DescriptionListTerm>searches</DescriptionListTerm>
        <DescriptionListDescription>
          {metadata.searches ?? '—'} / {metadata.search_limit ?? '—'}
        </DescriptionListDescription>
      </DescriptionListGroup>
      <DescriptionListGroup>
        <DescriptionListTerm>evidence</DescriptionListTerm>
        <DescriptionListDescription>{metadata.evidence_status ?? '—'}</DescriptionListDescription>
      </DescriptionListGroup>
      <DescriptionListGroup>
        <DescriptionListTerm>clarification</DescriptionListTerm>
        <DescriptionListDescription>
          {metadata.clarification_used ? 'used' : 'not used'}
        </DescriptionListDescription>
      </DescriptionListGroup>
      <DescriptionListGroup>
        <DescriptionListTerm>model requests</DescriptionListTerm>
        <DescriptionListDescription>{metadata.llm_requests ?? '—'}</DescriptionListDescription>
      </DescriptionListGroup>
      <DescriptionListGroup>
        <DescriptionListTerm>tokens</DescriptionListTerm>
        <DescriptionListDescription>
          {Number.isFinite(metadata.llm_tokens) ? metadata.llm_tokens.toLocaleString() : '—'}
        </DescriptionListDescription>
      </DescriptionListGroup>
      <DescriptionListGroup>
        <DescriptionListTerm>limits hit</DescriptionListTerm>
        <DescriptionListDescription>
          {limits.length === 0
            ? 'none'
            : limits.map((limit) => (
                <Label isCompact color="orange" key={limit}>
                  {limit}
                </Label>
              ))}
        </DescriptionListDescription>
      </DescriptionListGroup>
      {metadata.error && (
        <DescriptionListGroup>
          <DescriptionListTerm>error</DescriptionListTerm>
          <DescriptionListDescription>
            <Label isCompact color="red">{metadata.error}</Label>
          </DescriptionListDescription>
        </DescriptionListGroup>
      )}
      <DescriptionListGroup>
        <DescriptionListTerm>task id</DescriptionListTerm>
        <DescriptionListDescription>
          <ClipboardCopy hoverTip="Copy" clickTip="Copied" isReadOnly variant="inline-compact">
            {task?.id ?? '—'}
          </ClipboardCopy>
        </DescriptionListDescription>
      </DescriptionListGroup>
      <DescriptionListGroup>
        <DescriptionListTerm>context id</DescriptionListTerm>
        <DescriptionListDescription>
          <ClipboardCopy hoverTip="Copy" clickTip="Copied" isReadOnly variant="inline-compact">
            {task?.contextId ?? '—'}
          </ClipboardCopy>
        </DescriptionListDescription>
      </DescriptionListGroup>
    </DescriptionList>
  )
}

function Evidence({ metadata }) {
  const evidence = Array.isArray(metadata?.evidence) ? metadata.evidence : []
  if (evidence.length === 0) {
    return <p className="ka-muted">This run returned no structured references.</p>
  }
  return (
    <Table aria-label="Evidence" variant="compact" borders={false}>
      <Thead>
        <Tr>
          <Th>support</Th>
          <Th>source</Th>
          <Th>title</Th>
          <Th>document</Th>
          <Th>search</Th>
        </Tr>
      </Thead>
      <Tbody>
        {evidence.map((entry, index) => (
          <Tr key={`${entry.document_id ?? index}-${index}`}>
            <Td dataLabel="support">{supportLabel(entry.support)}</Td>
            <Td dataLabel="source">
              <span className="ka-mono">{entry.source ?? '—'}</span>
            </Td>
            <Td dataLabel="title">
              {entry.url ? (
                <a href={entry.url} target="_blank" rel="noreferrer noopener">
                  {sourceLabel(entry)}
                </a>
              ) : (
                sourceLabel(entry)
              )}
            </Td>
            <Td dataLabel="document">
              <span className="ka-mono">{entry.document_id ?? '—'}</span>
            </Td>
            <Td dataLabel="search">{entry.search ?? '—'}</Td>
          </Tr>
        ))}
      </Tbody>
    </Table>
  )
}

function Raw({ raw, card }) {
  const last = raw.length > 0 ? raw[raw.length - 1] : null
  return (
    <div className="ka-raw">
      <h4>Last exchange</h4>
      {last ? (
        <>
          <CodeBlock>
            <CodeBlockCode>{JSON.stringify(last.request, null, 2)}</CodeBlockCode>
          </CodeBlock>
          <CodeBlock>
            <CodeBlockCode>{JSON.stringify(last.response, null, 2)}</CodeBlockCode>
          </CodeBlock>
        </>
      ) : (
        <p className="ka-muted">No A2A exchange yet.</p>
      )}
      <details className="ka-card-details">
        <summary>Discovered Agent Card</summary>
        <CodeBlock>
          <CodeBlockCode>
            {card ? JSON.stringify(card, null, 2) : 'Not loaded yet.'}
          </CodeBlockCode>
        </CodeBlock>
      </details>
    </div>
  )
}

export default function Inspector({ task, metadata, raw, card }) {
  const [activeKey, setActiveKey] = useState('workflow')
  const exchanges = useMemo(() => (Array.isArray(raw) ? raw : []), [raw])

  return (
    <Tabs
      activeKey={activeKey}
      onSelect={(_event, key) => setActiveKey(key)}
      isBox
      className="ka-tabs"
    >
      <Tab eventKey="workflow" title={<TabTitleText>Workflow</TabTitleText>}>
        <Workflow metadata={metadata} task={task} />
      </Tab>
      <Tab eventKey="evidence" title={<TabTitleText>Evidence</TabTitleText>}>
        <Evidence metadata={metadata} />
      </Tab>
      <Tab eventKey="raw" title={<TabTitleText>Raw</TabTitleText>}>
        <Raw raw={exchanges} card={card} />
      </Tab>
    </Tabs>
  )
}
