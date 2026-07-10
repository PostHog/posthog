import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ErrorTrackingFingerprint } from 'lib/components/Errors/types'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { errorTrackingIssuesResolveRetrieve } from '../../generated/api'
import type { ErrorTrackingIssueResolveResponseApi } from '../../generated/api.schemas'
import {
    ErrorTrackingIssueSceneLogicProps,
    errorTrackingIssueSceneLogic,
    parseErrorTrackingIssueSceneIdentifier,
} from './errorTrackingIssueSceneLogic'

jest.mock('../../generated/api', () => ({
    ...jest.requireActual('../../generated/api'),
    errorTrackingIssuesResolveRetrieve: jest.fn(),
}))

const ISSUE_ID = '00000000-0000-4000-8000-000000000001'

const makeResolvedIssue = (
    overrides: Partial<ErrorTrackingIssueResolveResponseApi> = {}
): ErrorTrackingIssueResolveResponseApi => ({
    id: ISSUE_ID,
    fingerprint: 'fp-1',
    status: 'active',
    name: 'TypeError',
    description: 'Something broke',
    first_seen: '2026-01-01T00:00:00Z',
    assignee: null,
    external_issues: [],
    cohort: null,
    matched_by: 'fingerprint',
    ...overrides,
})

const makeFingerprints = (fingerprint: string = 'fp-1'): ErrorTrackingFingerprint[] => [
    { fingerprint, issue_id: ISSUE_ID, created_at: '2026-01-01T00:00:00Z' },
]

describe('errorTrackingIssueSceneLogic', () => {
    let logic: ReturnType<typeof errorTrackingIssueSceneLogic.build>
    const mockResolveIssue = jest.mocked(errorTrackingIssuesResolveRetrieve)

    const mountLogic = (props: ErrorTrackingIssueSceneLogicProps = { identifier: 'fp-1' }): void => {
        logic = errorTrackingIssueSceneLogic(props)
        logic.mount()
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/error_tracking/fingerprints': [],
                '/api/environments/:team_id/error_tracking/spike_events/': { count: 0, results: [] },
            },
            post: {
                '/api/environments/:team_id/query/:kind/': { results: [] },
            },
        })
        initKeaTests()
        mockResolveIssue.mockResolvedValue(makeResolvedIssue())
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('round-trips a fingerprint through one encoded URL path segment', () => {
        const fingerprint = 'a/b ?#%+ü'
        const issueUrl = urls.errorTrackingIssue(fingerprint)

        expect(issueUrl).toBe('/error_tracking/a%2Fb%20%3F%23%25%2B%C3%BC')
        expect(parseErrorTrackingIssueSceneIdentifier(issueUrl.replace('/error_tracking/', ''))).toEqual({
            identifier: fingerprint,
            legacyFingerprint: false,
        })
        expect(parseErrorTrackingIssueSceneIdentifier('path%2Ffingerprint', '')).toEqual({
            identifier: 'path/fingerprint',
            legacyFingerprint: false,
        })
    })

    it('waits for identifier resolution before loading issue data', async () => {
        let resolveIssue: (issue: ErrorTrackingIssueResolveResponseApi) => void = () => {}
        mockResolveIssue.mockReturnValueOnce(
            new Promise<ErrorTrackingIssueResolveResponseApi>((resolve) => {
                resolveIssue = resolve
            })
        )
        const querySpy = jest.spyOn(api, 'query')
        const issueQueryCalls = (): typeof querySpy.mock.calls =>
            querySpy.mock.calls.filter(([query]) => query.kind === 'ErrorTrackingQuery')

        mountLogic()

        expect(mockResolveIssue).toHaveBeenCalledWith(expect.any(String), { identifier: 'fp-1' })
        expect(issueQueryCalls()).toHaveLength(0)

        resolveIssue(makeResolvedIssue())
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.issueId).toBe(ISSUE_ID)
        expect(issueQueryCalls().length).toBeGreaterThan(0)
    })

    it.each([
        [
            'legacy issue ID',
            `/error_tracking/${ISSUE_ID}?timestamp=2026-01-02T00%3A00%3A00Z&utm_source=alert#panel=activity`,
            { identifier: ISSUE_ID, isScene: true },
            makeResolvedIssue({ matched_by: 'issue_id', fingerprint: 'a/b' }),
        ],
        [
            'legacy fingerprint query',
            `/error_tracking/${ISSUE_ID}?fingerprint=a%2Fb&timestamp=2026-01-02T00%3A00%3A00Z&utm_source=alert#panel=activity`,
            { identifier: 'a/b', legacyFingerprint: true, isScene: true },
            makeResolvedIssue({ matched_by: 'fingerprint', fingerprint: 'a/b' }),
        ],
    ] as const)('canonicalizes a %s while preserving URL state', async (_name, initialUrl, props, response) => {
        router.actions.push(initialUrl)
        mockResolveIssue.mockResolvedValueOnce(response)
        mountLogic(props)

        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.currentLocation.pathname).toBe(urls.currentProject(urls.errorTrackingIssue('a/b')))
        expect(router.values.searchParams).toEqual({
            timestamp: '2026-01-02T00:00:00Z',
            utm_source: 'alert',
        })
        expect(router.values.hashParams).toEqual({ panel: 'activity' })
    })

    // eventsQueryKey is the kea key of the events table's data source logic: every key change
    // unmounts and remounts the whole table tree. It used to be uuid() per recompute, so even a
    // deep-equal fingerprints refetch rebuilt the table. These lock in the key contract both ways.
    it('keeps eventsQuery and eventsQueryKey stable across deep-equal fingerprint loads', () => {
        mountLogic()
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
        mountLogic()
        logic.actions.loadIssueFingerprintsSuccess(makeFingerprints())
        const initialKey = logic.values.eventsQueryKey

        mutate(logic)

        expect(logic.values.eventsQueryKey).not.toBe(initialKey)
    })
})
