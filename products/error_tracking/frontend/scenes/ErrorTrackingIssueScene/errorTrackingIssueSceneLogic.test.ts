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
})
