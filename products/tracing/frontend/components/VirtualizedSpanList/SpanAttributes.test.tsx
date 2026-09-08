import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType } from '~/types'

import { SpanAttributes } from './SpanAttributes'

// The branch under test is which component a value renders as, not the link internals:
// both targets mount their own data-fetching logics, so they're stubbed at the boundary.
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

describe('SpanAttributes correlation links', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:teamId/tracing_config/': () => [
                    200,
                    {
                        tracing_distinct_id_attribute_keys: ['posthogDistinctId'],
                        tracing_session_id_attribute_keys: ['sessionId', 'my.custom.session'],
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

    it('renders person and replay links for matching keys, plain text otherwise', () => {
        render(
            <SpanAttributes
                title="Attributes"
                attributes={{ posthogDistinctId: 'user-1', sessionId: 'session-1', 'http.method': 'GET' }}
                propertyType={PropertyFilterType.SpanAttribute}
            />
        )

        expect(screen.getByText('user-1')).toHaveAttribute('data-attr', 'mock-person-display')
        expect(screen.getByText('session-1')).toHaveAttribute('data-attr', 'mock-view-recording')
        expect(screen.getByText('GET')).not.toHaveAttribute('data-attr')
    })

    it('links a session id under a team-configured custom key once the config loads', async () => {
        const { container } = render(
            <SpanAttributes
                title="Attributes"
                attributes={{ 'my.custom.session': 'session-2' }}
                propertyType={PropertyFilterType.SpanAttribute}
            />
        )

        // The custom key only matches after the mocked tracing_config resolves; until then the
        // value renders as plain text, so wait for the link element rather than the text.
        await waitFor(() =>
            expect(container.querySelector('[data-attr="mock-view-recording"]')).toHaveTextContent('session-2')
        )
    })

    it('renders plain text when the flag is off', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})

        const { container } = render(
            <SpanAttributes
                title="Attributes"
                attributes={{ sessionId: 'session-1' }}
                propertyType={PropertyFilterType.SpanAttribute}
            />
        )

        expect(screen.getAllByText('session-1').length).toBeGreaterThan(0)
        expect(container.querySelector('[data-attr="mock-view-recording"]')).toBeNull()
    })

    it('never links values in the synthetic details table (no propertyType)', () => {
        const { container } = render(
            <SpanAttributes title="Span details" attributes={{ 'session.id': 'session-3' }} showFilterActions={false} />
        )

        expect(screen.getAllByText('session-3').length).toBeGreaterThan(0)
        expect(container.querySelector('[data-attr="mock-view-recording"]')).toBeNull()
    })
})
