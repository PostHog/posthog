import { expectLogic } from 'kea-test-utils'

import { ErrorTrackingFingerprint } from 'lib/components/Errors/types'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

const makeFingerprints = (fingerprint: string = 'fp-1'): ErrorTrackingFingerprint[] => [
    { fingerprint, issue_id: 'issue-1', created_at: '2026-01-01T00:00:00Z' },
]

describe('errorTrackingIssueSceneLogic', () => {
    let logic: ReturnType<typeof errorTrackingIssueSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/error_tracking/issues/:id/': {},
                '/api/environments/:team_id/error_tracking/issues/:id/fingerprints/': [],
            },
            post: {
                '/api/environments/:team_id/query/': { results: [] },
            },
        })
        initKeaTests()
        logic = errorTrackingIssueSceneLogic({ id: 'issue-1' })
        logic.mount()
    })

    afterEach(() => logic?.unmount())

    // eventsQueryKey is the kea key of the events table's data source logic: every key change
    // unmounts and remounts the whole table tree. It used to be uuid() per recompute, so even a
    // deep-equal fingerprints refetch rebuilt the table. These lock in the key contract both ways.
    it('keeps eventsQuery and eventsQueryKey stable across deep-equal fingerprint loads', () => {
        logic.actions.loadIssueFingerprintsSuccess(makeFingerprints())
        const initialQuery = logic.values.eventsQuery
        const initialKey = logic.values.eventsQueryKey

        // Freshly constructed but deep-equal — as a refetch would deliver.
        logic.actions.loadIssueFingerprintsSuccess(makeFingerprints())

        expect(logic.values.eventsQuery).toBe(initialQuery)
        expect(logic.values.eventsQueryKey).toBe(initialKey)
    })

    it.each<[string, (logic: ReturnType<typeof errorTrackingIssueSceneLogic.build>) => void]>([
        ['fingerprints change', (l) => l.actions.loadIssueFingerprintsSuccess(makeFingerprints('fp-2'))],
        ['search query changes', (l) => l.actions.setSearchQuery('needle')],
    ])('changes eventsQueryKey when the %s', (_name, mutate) => {
        logic.actions.loadIssueFingerprintsSuccess(makeFingerprints())
        const initialKey = logic.values.eventsQueryKey

        mutate(logic)

        expect(logic.values.eventsQueryKey).not.toBe(initialKey)
    })

    it('handles an empty initial event query result', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadInitialEvent('2026-01-01T00:00:00Z')
        })
            .toDispatchActions(['loadInitialEventSuccess'])
            .toMatchValues({ initialEvent: null })
    })

    // A malformed `timestamp` URL param used to be stored and fed to getNarrowDateRange, where
    // dayjs().toISOString() threw a RangeError and crashed the whole scene on mount. It must now
    // be ignored so the scene falls back to the valid server-provided timestamp.
    it.each(['not-a-date', 'undefined', '2026-01-02T03%3A04%3A05'])(
        'ignores a malformed initial event timestamp (%s)',
        (bad) => {
            logic.actions.setInitialEventTimestamp(bad)
            expect(logic.values.initialEventTimestamp).toBeNull()

            // A valid timestamp (as the server's last_seen provides) is still accepted afterwards.
            logic.actions.setInitialEventTimestamp('2026-01-02T03:04:05Z')
            expect(logic.values.initialEventTimestamp).toBe('2026-01-02T03:04:05Z')
        }
    )
})
