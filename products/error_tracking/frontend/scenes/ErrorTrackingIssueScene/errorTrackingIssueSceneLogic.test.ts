import { expectLogic } from 'kea-test-utils'

import { ErrorTrackingFingerprint } from 'lib/components/Errors/types'
import type { ErrorEventType } from 'lib/components/Errors/types'

import { useMocks } from '~/mocks/jest'
import type { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { errorTrackingIssueSceneLogic, toErrorTrackingIssueSummary } from './errorTrackingIssueSceneLogic'
import { linkedReportsLogic } from './linkedReportsLogic'

const VALID_ISSUE_ID = '01890a1b-2c3d-4e4f-8a9b-0c1d2e3f4a5b'
const ISSUE: ErrorTrackingRelationalIssue = {
    id: VALID_ISSUE_ID,
    name: 'TypeError',
    description: 'Something broke',
    assignee: null,
    status: 'active',
    severity: 'low',
    first_seen: '2026-01-01T00:00:00Z',
}

const makeFingerprints = (fingerprint: string = 'fp-1'): ErrorTrackingFingerprint[] => [
    { fingerprint, issue_id: VALID_ISSUE_ID, created_at: '2026-01-01T00:00:00Z' },
]

describe('errorTrackingIssueSceneLogic', () => {
    let logic: ReturnType<typeof errorTrackingIssueSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/error_tracking/issues/:id/': ISSUE,
                '/api/environments/:team_id/error_tracking/issues/:id/fingerprints/': [],
                // Fails by default, so every test in this file also proves the panel degrades quietly.
                '/api/projects/:team_id/signals/reports/': () => [500, { detail: 'ClickHouse is unhappy' }],
            },
            post: {
                '/api/environments/:team_id/query/': { results: [] },
            },
            patch: {
                '/api/projects/:team_id/error_tracking/issues/:id/': ISSUE,
            },
        })
        initKeaTests()
        logic = errorTrackingIssueSceneLogic({ id: VALID_ISSUE_ID })
        logic.mount()
    })

    afterEach(() => logic?.unmount())

    // The catch-all `/error_tracking/:id` route can capture a legacy settings slug. Without the
    // guard the scene fired every loader against a non-UUID id, spraying "issue_id must be a valid
    // UUID" toasts over a blank page.
    it.each(['symbol_sets', 'symbol-sets', 'settings', 'configuration'])(
        'marks a non-UUID id as invalid and skips the loaders (%s)',
        async (id) => {
            const scopedLogic = errorTrackingIssueSceneLogic({ id })
            await expectLogic(scopedLogic, () => {
                scopedLogic.mount()
            }).toNotHaveDispatchedActions(['loadIssue'])
            expect(scopedLogic.values.issueIdValid).toBe(false)
            scopedLogic.unmount()
        }
    )

    it('loads the issue when the id is a valid UUID', async () => {
        const scopedLogic = errorTrackingIssueSceneLogic({ id: VALID_ISSUE_ID })
        await expectLogic(scopedLogic, () => {
            scopedLogic.mount()
        }).toDispatchActions(['loadIssue'])
        expect(scopedLogic.values.issueIdValid).toBe(true)
        scopedLogic.unmount()
    })

    it('keeps the events query stable when the loaded fingerprints change', () => {
        logic.actions.loadIssueFingerprintsSuccess(makeFingerprints())
        const initialQuery = logic.values.eventsQuery
        const initialKey = logic.values.eventsQueryKey

        logic.actions.loadIssueFingerprintsSuccess(makeFingerprints('fp-2'))

        expect(logic.values.eventsQuery).toBe(initialQuery)
        expect(logic.values.eventsQueryKey).toBe(initialKey)
    })

    it('leaves linked reports empty and does not fail when the signals lookup errors', async () => {
        // Letting the loader reject would toast an error on every issue page during a signals outage.
        const reportsLogic = linkedReportsLogic({ issueId: VALID_ISSUE_ID })
        await expectLogic(reportsLogic).toDispatchActions(['loadLinkedReportsSuccess']).toMatchValues({
            linkedReports: [],
        })
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

    it('allows the event selection to close', () => {
        const event = { uuid: 'event-1' } as ErrorEventType
        logic.actions.selectEvent(event)
        logic.actions.selectEvent(null)

        expect(logic.values.selectedEvent).toBeNull()
    })

    it('updates severity on the issue detail and persists it', async () => {
        await expectLogic(logic, () => {
            logic.actions.setIssue(ISSUE)
            logic.actions.updateSeverity('critical')
        })
            .toDispatchActions(['updateIssueSeverity'])
            .toMatchValues({ issue: expect.objectContaining({ severity: 'critical' }) })
    })

    it('restores the persisted severity when an update fails', async () => {
        logic.actions.setIssue({ ...ISSUE, severity: 'critical' })

        await expectLogic(logic, () => {
            logic.actions.mutationFailure('updateIssueSeverity', new Error('Update failed'))
        })
            .toDispatchActions(['loadIssueSuccess'])
            .toMatchValues({ issue: expect.objectContaining({ severity: 'low' }) })
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
