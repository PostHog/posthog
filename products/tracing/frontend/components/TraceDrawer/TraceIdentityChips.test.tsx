import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { Span } from '../../types'
import { TraceIdentityChips } from './TraceIdentityChips'

// The branch under test is whether the chips render at all, not the link internals: both targets
// mount their own data-fetching logics, so they're stubbed at the boundary.
jest.mock('scenes/persons/PersonDisplay', () => ({
    PersonDisplay: ({ person }: { person: { distinct_id: string } }) => (
        <div data-attr="mock-person-display">{person.distinct_id}</div>
    ),
}))
jest.mock('lib/components/ViewRecordingButton/ViewRecordingButton', () => ({
    __esModule: true,
    default: ({ sessionId }: { sessionId: string }) => <div data-attr="mock-view-recording">{sessionId}</div>,
    RecordingPlayerType: { Modal: 'modal' },
    ViewRecordingButtonVariant: { Link: 'link' },
}))

function span(overrides: Partial<Span>): Span {
    return {
        uuid: 'uuid',
        trace_id: 'trace-1',
        span_id: 'span-1',
        parent_span_id: '',
        name: 'GET /checkout',
        kind: 2,
        service_name: 'checkout-api',
        status_code: 0,
        timestamp: '2026-09-03T10:00:00Z',
        end_time: '2026-09-03T10:00:01Z',
        duration_nano: 1_000_000,
        is_root_span: true,
        matched_filter: true,
        attributes: {},
        resource_attributes: {},
        ...overrides,
    }
}

describe('TraceIdentityChips', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:teamId/tracing_config/': () => [
                    200,
                    {
                        tracing_distinct_id_attribute_keys: ['posthogDistinctId'],
                        tracing_session_id_attribute_keys: ['sessionId'],
                    },
                ],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TRACING_SESSION_PERSON_LINKS], {
            [FEATURE_FLAGS.TRACING_SESSION_PERSON_LINKS]: true,
        })
    })

    it('renders the person and the recording link for a trace that carries both', () => {
        const { container } = render(
            <TraceIdentityChips
                spans={[span({ attributes: { posthogDistinctId: 'user-1', sessionId: 'session-1' } })]}
                timestamp="2026-09-03T10:00:00Z"
            />
        )

        expect(container.querySelector('[data-attr="mock-person-display"]')).toHaveTextContent('user-1')
        expect(container.querySelector('[data-attr="mock-view-recording"]')).toHaveTextContent('session-1')
    })

    it('renders nothing for a trace that carries no identity', () => {
        const { container } = render(
            <TraceIdentityChips spans={[span({ attributes: { 'http.method': 'GET' } })]} timestamp={null} />
        )

        expect(container).toBeEmptyDOMElement()
    })

    it('renders nothing when the flag is off', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})

        const { container } = render(
            <TraceIdentityChips
                spans={[span({ attributes: { posthogDistinctId: 'user-1', sessionId: 'session-1' } })]}
                timestamp={null}
            />
        )

        expect(container).toBeEmptyDOMElement()
    })
})
