import { expectLogic } from 'kea-test-utils'

import { ErrorTrackingFingerprint } from 'lib/components/Errors/types'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { errorTrackingIssueSceneLogic, toErrorTrackingIssueSummary } from './errorTrackingIssueSceneLogic'

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

    it('keeps the events query stable when the loaded fingerprints change', () => {
        logic.actions.loadIssueFingerprintsSuccess(makeFingerprints())
        const initialQuery = logic.values.eventsQuery
        const initialKey = logic.values.eventsQueryKey

        logic.actions.loadIssueFingerprintsSuccess(makeFingerprints('fp-2'))

        expect(logic.values.eventsQuery).toBe(initialQuery)
        expect(logic.values.eventsQueryKey).toBe(initialKey)
    })

    it('changes the events query key when the search query changes', () => {
        const initialKey = logic.values.eventsQueryKey

        logic.actions.setSearchQuery('needle')

        expect(logic.values.eventsQueryKey).not.toBe(initialKey)
    })

    it('handles an empty initial event query result', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadInitialEvent('2026-01-01T00:00:00Z')
        })
            .toDispatchActions(['loadInitialEventSuccess'])
            .toMatchValues({ initialEvent: null })
    })

    it('keeps stable first and last event IDs in the issue summary', () => {
        expect(
            toErrorTrackingIssueSummary({
                first_seen: '2026-01-01T00:00:00Z',
                last_seen: '2026-01-02T00:00:00Z',
                first_event: {
                    uuid: 'first-event',
                    distinct_id: 'first-person',
                    timestamp: '2026-01-01T00:00:00Z',
                    properties: '{}',
                },
                last_event: {
                    uuid: 'last-event',
                    distinct_id: 'last-person',
                    timestamp: '2026-01-02T00:00:00Z',
                    properties: '{}',
                },
                aggregations: { occurrences: 2, sessions: 2, users: 2, volume_buckets: [] },
            })
        ).toEqual({
            first_seen: '2026-01-01T00:00:00Z',
            last_seen: '2026-01-02T00:00:00Z',
            first_event_uuid: 'first-event',
            last_event_uuid: 'last-event',
            aggregations: { occurrences: 2, sessions: 2, users: 2, volume_buckets: [] },
        })
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
