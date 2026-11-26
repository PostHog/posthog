import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { maxMocks } from 'scenes/max/testUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ParsedLogMessage } from 'products/logs/frontend/types'

import { LogContextLinks } from './LogContextLinks'

const log = {
    uuid: 'log-1',
    timestamp: '2026-10-12T09:43:23.143Z',
    trace_id: '',
    span_id: '',
    attributes: {},
    resource_attributes: { 'service.name': 'checkout-api' },
    cleanBody: 'payment failed',
    severity_text: 'error',
} as unknown as ParsedLogMessage

describe('LogContextLinks', () => {
    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
    })

    afterEach(cleanup)

    it('offers to find out why when a log has no trace, session, or person link', () => {
        render(<LogContextLinks log={log} surface="drawer" onOpenRelatedErrors={() => {}} />)

        expect(screen.getByText('Trace, session, and person links missing.')).toBeInTheDocument()
        expect(screen.getByText('Find out why')).toBeInTheDocument()
    })
})
