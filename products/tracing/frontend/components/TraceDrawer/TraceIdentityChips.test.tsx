import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import type { TraceIdentity } from '../../traceIdentity'
import { TraceIdentityChips } from './TraceIdentityChips'

// The branch under test is which chips render for a resolved identity, not the link internals:
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

describe('TraceIdentityChips', () => {
    function renderChips(identity: TraceIdentity): HTMLElement {
        const { container } = render(<TraceIdentityChips identity={identity} timestamp="2026-09-03T10:00:00Z" />)
        return container
    }

    // Each chip is independent, so a trace with only one half still shows that half.
    test.each<TraceIdentity>([
        { distinctId: 'user-1', sessionId: 'session-1' },
        { distinctId: null, sessionId: 'session-1' },
        { distinctId: 'user-1', sessionId: null },
    ])('renders the chips for %j', (identity) => {
        const container = renderChips(identity)

        expect(container.querySelector('[data-attr="mock-person-display"]')?.textContent ?? null).toBe(
            identity.distinctId
        )
        expect(container.querySelector('[data-attr="mock-view-recording"]')?.textContent ?? null).toBe(
            identity.sessionId
        )
    })

    it('renders nothing for a trace with no identity', () => {
        expect(renderChips({ distinctId: null, sessionId: null })).toBeEmptyDOMElement()
    })
})
