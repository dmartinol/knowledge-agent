// One-click prompts. They only prefill the composer; nothing is sent.

export const SCENARIOS = [
  {
    id: 'evidence',
    label: 'Evidence-backed answer',
    hint: 'A question LCORE can answer from Red Hat documentation.',
    prompt:
      'Explain how an OpenShift Route exposes a Service, including default hostname generation and TLS termination options.',
  },
  {
    id: 'ambiguous',
    label: 'Ambiguous request',
    hint: 'Deliberately under-specified, so the agent should ask one question.',
    prompt: 'Tell me about it.',
  },
  {
    id: 'no-evidence',
    label: 'No evidence',
    hint: 'Expected to come back labelled unverified.',
    prompt: 'What is the internal release date for the next major version of this product?',
  },
  {
    id: 'follow-up',
    label: 'Follow-up search',
    hint: 'Encourages a second, narrower search.',
    prompt:
      'Compare edge and re-encrypt TLS termination on an OpenShift Route, including which one needs the Service to serve TLS.',
  },
  {
    id: 'limit',
    label: 'Search limit',
    hint: 'Broad enough that the two-search cap becomes visible.',
    prompt:
      'Give me a complete overview of OpenShift networking, including Routes, Ingress, Services, and DNS.',
  },
]
