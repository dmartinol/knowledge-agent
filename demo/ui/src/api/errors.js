// Stable agent failure categories mapped to demo-friendly copy.

const ERROR_COPY = {
  model_config_error: {
    title: 'The reasoning model rejected its configuration',
    detail: 'The provider refused the configured credentials or model name.',
  },
  model_unavailable: {
    title: 'The reasoning model is unreachable',
    detail: 'The agent could not connect to the model provider.',
  },
  model_timeout: {
    title: 'The reasoning model timed out',
    detail: 'The provider did not answer within the configured model timeout.',
  },
  model_limit: {
    title: 'The reasoning budget ran out',
    detail: 'The run hit the model request or token limit before an answer was ready.',
  },
  model_output_invalid: {
    title: 'The model returned an unusable answer',
    detail: 'The final output failed validation, so no answer was delivered.',
  },
  card_unavailable: {
    title: 'The knowledge service card is unavailable',
    detail: 'The agent could not read the LCORE Agent Card.',
  },
  protocol_unsupported: {
    title: 'The knowledge service speaks an unsupported protocol',
    detail: 'LCORE did not advertise a compatible A2A protocol version.',
  },
  timeout: {
    title: 'The knowledge service timed out',
    detail: 'The upstream search did not answer within the LCORE client timeout.',
  },
  http_error: {
    title: 'The agent interface failed',
    detail: 'The A2A endpoint answered with an HTTP error.',
  },
  jsonrpc_error: {
    title: 'The agent rejected the request',
    detail: 'The A2A endpoint answered with a JSON-RPC error.',
  },
  task_not_completed: {
    title: 'The knowledge service did not finish the search',
    detail: 'LCORE returned a task that never reached a completed state.',
  },
  invalid_response: {
    title: 'The knowledge service returned an unexpected answer',
    detail: 'LCORE answered with a shape the agent could not decode.',
  },
  deadline: {
    title: 'The run hit its deadline',
    detail: 'The task deadline passed before an answer was ready.',
  },
  skills_unavailable: {
    title: 'The agent skills could not be loaded',
    detail: 'The skills tree or one of its packages was unusable.',
  },
  rejected: {
    title: 'The agent is at capacity',
    detail: 'Every concurrent task slot was busy, so this request was rejected.',
  },
  ui_timeout: {
    title: 'The run is taking too long',
    detail: 'The console stopped waiting after its own polling limit.',
  },
}

const FALLBACK = {
  title: 'The run failed',
  detail: 'The agent reported a failure the console does not recognise yet.',
}

export function describeError(code) {
  const copy = ERROR_COPY[code] ?? FALLBACK
  return { ...copy, code: code || 'unknown' }
}
