import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { featureFlagFilterSummaryLogic } from './featureFlagFilterSummaryLogic'

describe('featureFlagFilterSummaryLogic', () => {
    test.each([
        [
            'summarizes a multivariate flag',
            [
                {
                    key: 'my-flag',
                    active: true,
                    filters: {
                        groups: [{ rollout_percentage: 100 }, { rollout_percentage: 50 }],
                        multivariate: {
                            variants: [
                                { key: 'control', rollout_percentage: 50 },
                                { key: 'test', rollout_percentage: 50 },
                            ],
                        },
                    },
                },
            ],
            {
                active: true,
                archived: false,
                conditionCount: 2,
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        ],
        [
            'summarizes a disabled boolean flag',
            [{ key: 'my-flag', active: false, filters: { groups: [{ rollout_percentage: 100 }] } }],
            { active: false, archived: false, conditionCount: 1, variants: [] },
        ],
        [
            'leaves conditions out for a flag config the UI cannot read',
            [{ key: 'my-flag', active: true, filters: { version: 2, rules: [] } }],
            { active: true, archived: false, conditionCount: null, variants: null },
        ],
        [
            'treats a flag with empty filters as a boolean flag with no conditions',
            [{ key: 'my-flag', active: true, filters: {} }],
            { active: true, archived: false, conditionCount: 0, variants: [] },
        ],
        ['has no summary when no flag has the key', [], null],
        [
            'finds an archived flag when no live flag has the key',
            [{ key: 'my-flag', active: false, archived: true, filters: { groups: [] } }],
            { active: false, archived: true, conditionCount: 0, variants: [] },
        ],
        [
            'picks the flag whose key matches in the same case',
            [
                { key: 'MY-FLAG', active: false, filters: { groups: [] } },
                { key: 'my-flag', active: true, filters: { groups: [{ rollout_percentage: 100 }] } },
            ],
            { active: true, archived: false, conditionCount: 1, variants: [] },
        ],
    ])('%s', async (_name, results, expectedSummary) => {
        useMocks({
            get: {
                '/api/projects/:team_id/feature_flags/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const isLookupForKey = params.get('key') === 'my-flag'
                    const wantsArchived = params.get('archived') === 'true'
                    const matches = results.filter((flag) => !!flag.archived === wantsArchived)
                    return [200, { count: matches.length, results: isLookupForKey ? matches : [] }]
                },
            },
        })
        initKeaTests()
        const logic = featureFlagFilterSummaryLogic({ flagKey: 'my-flag' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ summary: expectedSummary })

        logic.unmount()
    })

    it('reuses a recent lookup when the logic mounts again', async () => {
        let requests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/feature_flags/': () => {
                    requests++
                    return [200, { count: 1, results: [{ key: 'my-flag', active: true, filters: { groups: [] } }] }]
                },
            },
        })
        initKeaTests()

        for (let mount = 0; mount < 2; mount++) {
            const logic = featureFlagFilterSummaryLogic({ flagKey: 'my-flag' })
            logic.mount()
            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({ summary: expect.objectContaining({ active: true }) })
            logic.unmount()
        }

        expect(requests).toBe(1)
    })
})
