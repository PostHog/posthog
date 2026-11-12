import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { recommendationsLogic } from './recommendationsLogic'

const RESOLUTIONS_URL = '/api/projects/:team_id/marketing_analytics_recommendation_resolutions/'
const QUERY_URL = '/api/environments/:team_id/query/MarketingAnalyticsRecommendationsQuery/'
const DISMISSED = { id: 'resolution-1', resolution: 'dismissed' as const, resolved_at: '2026-11-01T00:00:00Z' }

const RECOMMENDATION: MarketingAnalyticsRecommendation = {
    rule: 'spend_without_conversions',
    level: 'search_term',
    subject: 'example shoes',
    campaign: 'Search',
    identity: {
        rule: 'spend_without_conversions',
        source_type: 'google_ads',
        customer_id: '1234567890',
        campaign_id: '',
        subject: 'example shoes',
    },
    key: 'key-example-shoes',
    action: 'Add it as a negative keyword',
    reason: 'No conversions',
    impact: 100,
    impactDirection: 'save',
    impactType: 'measured',
    currency: 'USD',
}

describe('recommendationsLogic', () => {
    let logic: ReturnType<typeof recommendationsLogic.build>

    beforeEach(() => {
        useMocks({
            get: { '/api/environments/:team_id/external_data_sources/': { results: [] } },
            post: { [QUERY_URL]: { results: [RECOMMENDATION], disclaimer: '' } },
        })
        initKeaTests()
        logic = recommendationsLogic()
        logic.mount()
        // The section hands its query to the node the same way.
        dataNodeLogic(logic.values.dataNodeProps)
    })

    const respond = (results: MarketingAnalyticsRecommendation[]): void => {
        dataNodeLogic(logic.values.dataNodeProps).actions.loadDataSuccess({ results, disclaimer: '' })
    }

    it.each([
        {
            name: 'opening reports the entry point',
            run: () => logic.actions.openRecommendations('brand_leak', 'intro', 7),
            reported: () => marketingAnalyticsLogic.actionCreators.reportRecommendationsOpened('intro', 7),
        },
        {
            name: 'selecting a rule reports the rule',
            run: () => logic.actions.selectRule('keyword_gap', 3),
            reported: () => marketingAnalyticsLogic.actionCreators.reportRecommendationsRuleSelected('keyword_gap', 3),
        },
        {
            name: 'closing reports the rule that was open',
            run: () => {
                logic.actions.openRecommendations('brand_leak', 'button', 7)
                logic.actions.closeRecommendations()
            },
            reported: () => marketingAnalyticsLogic.actionCreators.reportRecommendationsClosed('brand_leak'),
        },
        {
            name: 'dismissing the intro reports it',
            run: () => logic.actions.dismissIntro(),
            reported: () => marketingAnalyticsLogic.actionCreators.reportRecommendationsIntroDismissed(),
        },
    ])('$name', async ({ run, reported }) => {
        await expectLogic(marketingAnalyticsLogic, run).toDispatchActions([reported()])
    })

    it.each(['dismissed', 'applied'] as const)(
        'hides a recommendation marked %s, reloads, and undoes it from the toast',
        async (resolution) => {
            let posted: Record<string, unknown> | undefined
            useMocks({
                post: {
                    [RESOLUTIONS_URL]: async ({ request }) => {
                        posted = (await request.json()) as Record<string, unknown>
                        return [
                            201,
                            {
                                id: 'resolution-1',
                                ...posted,
                                key: RECOMMENDATION.key,
                                resolved_by: null,
                                resolved_at: '2026-11-01T00:00:00Z',
                                created_at: '2026-11-01T00:00:00Z',
                            },
                        ]
                    },
                },
                delete: { [`${RESOLUTIONS_URL}:id/`]: [204] },
            })
            const toast = jest.spyOn(lemonToast, 'success')
            logic.actions.setShowResolved(true)

            await expectLogic(marketingAnalyticsLogic, () =>
                logic.actions.resolveRecommendation(RECOMMENDATION, resolution)
            ).toDispatchActions([
                marketingAnalyticsLogic.actionCreators.reportRecommendationResolved(
                    'spend_without_conversions',
                    'search_term',
                    resolution
                ),
            ])
            await expectLogic(logic).toDispatchActions(['loadData'])
            expect(posted).toEqual({ identity: RECOMMENDATION.identity, resolution, name: RECOMMENDATION.subject })
            expect(logic.values.resolutionOverrides[RECOMMENDATION.key]?.resolution).toBe(resolution)
            expect(logic.values.pendingKeys).toEqual([])

            await expectLogic(marketingAnalyticsLogic, () =>
                toast.mock.calls[0][1]?.button?.action()
            ).toDispatchActions([
                marketingAnalyticsLogic.actionCreators.reportRecommendationsActionClicked(
                    'undo',
                    'toast',
                    'spend_without_conversions'
                ),
                marketingAnalyticsLogic.actionCreators.reportRecommendationRestored(
                    'spend_without_conversions',
                    'search_term',
                    resolution
                ),
            ])
            expect(logic.values.resolutionOverrides[RECOMMENDATION.key]).toBeNull()
            expect(logic.values.pendingKeys).toEqual([])
            // The toggle hides with nothing resolved, so the next dismiss must not leave its row on screen.
            expect(logic.values.showResolved).toBe(false)
        }
    )

    it('keeps a dismissal hidden when a response that started before it arrives', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadDataSuccess'])
            .toMatchValues({ activeRecommendations: [RECOMMENDATION] })
        respond([RECOMMENDATION])
        logic.actions.resolutionSaved(RECOMMENDATION.key, DISMISSED)

        await expectLogic(logic, () => respond([RECOMMENDATION])).toMatchValues({ activeRecommendations: [] })
        expect(logic.values.resolutionOverrides).toEqual({ [RECOMMENDATION.key]: DISMISSED })

        await expectLogic(logic, () => respond([{ ...RECOMMENDATION, resolution: DISMISSED }])).toMatchValues({
            activeRecommendations: [],
            resolutionOverrides: {},
        })
    })

    it('keeps the open rule in view, with no rows, after its last recommendation is resolved', async () => {
        const other = { ...RECOMMENDATION, rule: 'keyword_gap' as const, key: 'key-other' }
        respond([RECOMMENDATION, other])
        logic.actions.openRecommendations('spend_without_conversions', 'button', 2)
        logic.actions.resolutionSaved(RECOMMENDATION.key, DISMISSED)

        expect(logic.values.selectedGroup).toMatchObject({
            rule: 'spend_without_conversions',
            recommendations: [],
            activeCount: 0,
        })

        await expectLogic(marketingAnalyticsLogic, () => logic.actions.selectRule('keyword_gap', 1)).toDispatchActions([
            marketingAnalyticsLogic.actionCreators.reportRecommendationsRuleSelected('keyword_gap', 1),
        ])
        expect(logic.values.groups.map((group) => group.rule)).toEqual(['keyword_gap'])
    })

    it('clears the pending state and reports nothing when resolving fails', async () => {
        useMocks({ post: { [RESOLUTIONS_URL]: () => [500, { detail: 'nope' }] } })

        await expectLogic(logic, () => logic.actions.resolveRecommendation(RECOMMENDATION, 'dismissed'))
            .toDispatchActions(['resolutionRequestFailed'])
            .toNotHaveDispatchedActions(['resolutionSaved'])
        expect(logic.values.resolutionOverrides).toEqual({})
        expect(logic.values.pendingKeys).toEqual([])
    })

    it('drops the local resolution when someone else already restored it', async () => {
        useMocks({ delete: { [`${RESOLUTIONS_URL}:id/`]: () => [404, { detail: 'Not found.' }] } })
        const resolved = { ...RECOMMENDATION, resolution: DISMISSED }

        await expectLogic(logic, () => logic.actions.restoreRecommendation(resolved))
            .toDispatchActions(['resolutionRemoved'])
            .toNotHaveDispatchedActions(['resolutionRequestFailed'])
        expect(logic.values.resolutionOverrides[RECOMMENDATION.key]).toBeNull()
        expect(logic.values.pendingKeys).toEqual([])
    })
})
