// Derives the view model from A2A results without parsing model prose.

export function isMessage(result) {
  return Boolean(result) && result.kind === 'message' && !result.status
}

export function textOf(parts) {
  if (!Array.isArray(parts)) return ''
  return parts
    .filter((part) => part && part.kind === 'text' && typeof part.text === 'string')
    .map((part) => part.text)
    .join('\n')
    .trim()
}

export function artifactOf(task) {
  const artifacts = task?.artifacts
  if (!Array.isArray(artifacts) || artifacts.length === 0) return null
  return artifacts[artifacts.length - 1]
}

export function workflowOf(task) {
  const artifact = artifactOf(task)
  return (
    artifact?.metadata?.knowledge_agent ??
    task?.status?.message?.metadata?.knowledge_agent ??
    null
  )
}

export function answerOf(task) {
  const artifact = artifactOf(task)
  if (!artifact) return null
  return textOf(artifact.parts) || null
}

export function clarificationOf(task) {
  if (task?.status?.state !== 'input-required') return null
  return textOf(task.status.message?.parts) || 'The agent needs more information.'
}

const FAILURE_STATE_CODES = {
  failed: 'unknown',
  rejected: 'rejected',
  canceled: 'canceled',
  'auth-required': 'auth_required',
  auth_required: 'auth_required',
}

export function failureOf(task) {
  const state = task?.status?.state
  if (!(state in FAILURE_STATE_CODES)) return null
  const workflow = workflowOf(task)
  return {
    code: workflow?.error ?? FAILURE_STATE_CODES[state],
    message: textOf(task.status?.message?.parts),
    limitsHit: Array.isArray(workflow?.limits_hit) ? workflow.limits_hit : [],
  }
}

export function splitAnswer(text) {
  const result = { body: '', gaps: [], sources: [], limitation: null }
  if (!text) return result
  const body = []
  let mode = 'body'
  for (const line of text.split('\n')) {
    if (line === 'Gaps:') {
      mode = 'gaps'
      continue
    }
    if (line === 'Sources:') {
      mode = 'sources'
      continue
    }
    if (line.startsWith('Limitation: ')) {
      result.limitation = line.slice('Limitation: '.length)
      mode = 'done'
      continue
    }
    if (mode === 'body') body.push(line)
    else if (mode === 'gaps' && line.startsWith('- ')) result.gaps.push(line.slice(2))
    else if (mode === 'sources' && line.startsWith('- ')) result.sources.push(line.slice(2))
  }
  result.body = body.join('\n').trim()
  return result
}

export function sourceLabel(entry) {
  return entry?.title || entry?.document_id || entry?.source || 'Untitled source'
}

export function retrievedSources(metadata) {
  const evidence = Array.isArray(metadata?.evidence) ? metadata.evidence : []
  return evidence
    .filter((entry) => entry?.support === 'retrieved')
    .map((entry) => ({
      label: sourceLabel(entry),
      url: entry.url ?? null,
      documentId: entry.document_id ?? null,
      source: entry.source ?? null,
    }))
}
