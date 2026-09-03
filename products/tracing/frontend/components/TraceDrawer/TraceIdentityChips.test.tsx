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
    // A trace can carry a person, a session, both, or neither, and each chip is independent.
    // Rendering an empty chip row for a server-only trace is the case worth guarding.
    test.each<[name: string, identity: TraceIdentity, person: string | null, recording: string | null]>([
        ['both', { distinctId: 'user-1', sessionId: 'session-1' }, 'user-1', 'session-1'],
        ['a session but no person', { distinctId: null, sessionId: 'session-1' }, null, 'session-1'],
        ['a person but no session', { distinctId: 'user-1', sessionId: null }, 'user-1', null],
        ['neither', { distinctId: null, sessionId: null }, null, null],
    ])('renders %s', (_name, identity, person, recording) => {
        const { container } = render(<TraceIdentityChips identity={identity} timestamp="2026-09-03T10:00:00Z" />)

        const personChip = container.querySelector('[data-attr="mock-person-display"]')
        const recordingChip = container.querySelector('[data-attr="mock-view-recording"]')
        expect(personChip?.textContent ?? null).toBe(person)
        expect(recordingChip?.textContent ?? null).toBe(recording)
        if (!person && !recording) {
            expect(container).toBeEmptyDOMElement()
        }
    })
})
