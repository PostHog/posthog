import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { errorTrackingFingerprintSceneLogic, rawFingerprintPathSegment } from './errorTrackingFingerprintSceneLogic'

describe('errorTrackingFingerprintSceneLogic', () => {
    let logic: ReturnType<typeof errorTrackingFingerprintSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/error_tracking/fingerprints/resolve/': {
                    id: 'fp-record-1',
                    fingerprint: 'fp-1',
                    issue_id: 'issue-1',
                    created_at: '2026-01-01T00:00:00Z',
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => logic?.unmount())

    it.each<[string, string | undefined, Record<string, string>]>([
        [
            'keeps the timestamp from the alert link',
            '2026-02-02T00:00:00Z',
            { fingerprint: 'fp-1', timestamp: '2026-02-02T00:00:00Z' },
        ],
        ['omits the timestamp when the link carried none', undefined, { fingerprint: 'fp-1' }],
    ])('redirects to the resolved issue and %s', async (_name, timestamp, expectedParams) => {
        logic = errorTrackingFingerprintSceneLogic({ fingerprint: 'fp-1', timestamp })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['resolveFingerprintSuccess'])

        expect(router.values.location.pathname).toMatch(/\/error_tracking\/issue-1$/)
        expect(router.values.searchParams).toEqual(expectedParams)
    })

    it('extracts the raw, still-encoded fingerprint segment from the pathname', () => {
        expect(rawFingerprintPathSegment('/project/1/error_tracking/fingerprint/%24uper%2Fstrange%23fp')).toEqual(
            '%24uper%2Fstrange%23fp'
        )
        expect(rawFingerprintPathSegment('/project/1/error_tracking/issue-id')).toBeNull()
    })
})
