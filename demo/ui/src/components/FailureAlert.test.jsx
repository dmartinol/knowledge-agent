import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import FailureAlert from './FailureAlert.jsx'

describe('FailureAlert', () => {
  it('maps a stable code to friendly copy and shows limit chips', () => {
    render(<FailureAlert code="model_limit" message="The request limit fired." limitsHit={['requests']} />)

    expect(screen.getByText('The reasoning budget ran out')).toBeInTheDocument()
    expect(screen.getByText('The request limit fired.')).toBeInTheDocument()
    expect(screen.getByText('model_limit')).toBeInTheDocument()
    expect(screen.getByText('limit: requests')).toBeInTheDocument()
  })

  it('falls back for codes the console does not know yet', () => {
    render(<FailureAlert code="brand_new_failure" message="Something odd." />)

    expect(screen.getByText('The run failed')).toBeInTheDocument()
    expect(screen.getByText('brand_new_failure')).toBeInTheDocument()
  })
})
