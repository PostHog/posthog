import type { QuarantineLiftEntryApi, QuarantinedIdentifierEntryApi, SnapshotApi } from '../generated/api.schemas'
import { groupCleanQuarantinedStories } from './liftOnMerge'

const snapshot = {
    id: 'snap',
    identifier: 'Components/Button--primary',
    current_artifact: { content_hash: 'rendered' },
}

const quarantine = { identifier: snapshot.identifier, reason: 'Hover state renders a frame late' }

function lift(state: QuarantineLiftEntryApi['state'], expectedHash: string): QuarantineLiftEntryApi {
    return { identifier: snapshot.identifier, state, expected_hash: expectedHash } as QuarantineLiftEntryApi
}

describe('liftOnMerge', () => {
    it.each([
        { name: 'no request', request: null, group: 'notRequested', expectsOtherPicture: false },
        {
            name: 'pending for this picture',
            request: lift('pending', 'rendered'),
            group: 'liftRequested',
            expectsOtherPicture: false,
        },
        {
            name: 'pending for an older picture',
            request: lift('pending', 'older'),
            group: 'liftRequested',
            expectsOtherPicture: true,
        },
        {
            name: 'pending without a linked artifact',
            request: lift('pending', 'older'),
            group: 'liftRequested',
            expectsOtherPicture: false,
            currentArtifact: null,
        },
        {
            name: 'cancelled for an older picture',
            request: lift('cancelled', 'older'),
            group: 'notRequested',
            expectsOtherPicture: false,
        },
    ])('groups a clean quarantined story with $name', ({ request, group, expectsOtherPicture, currentArtifact }) => {
        const rendered = currentArtifact === null ? { ...snapshot, current_artifact: null } : snapshot
        const groups = groupCleanQuarantinedStories(
            [rendered as SnapshotApi],
            request ? { [snapshot.identifier]: request } : {},
            [quarantine as QuarantinedIdentifierEntryApi]
        )

        const story = {
            snapshot: rendered,
            liftRequest: request,
            quarantineReason: quarantine.reason,
            expectsOtherPicture,
        }
        expect(groups).toEqual({ liftRequested: [], notRequested: [], [group]: [story] })
    })
})
