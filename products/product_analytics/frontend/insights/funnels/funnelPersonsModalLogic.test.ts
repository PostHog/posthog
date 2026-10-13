import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FunnelStep, FunnelStepWithConversionMetrics, InsightLogicProps, InsightShortId } from '~/types'

import { funnelPersonsModalLogic } from './funnelPersonsModalLogic'

jest.mock('scenes/trends/persons-modal/PersonsModal')

const Insight123 = '123' as InsightShortId

const makeSeries = (
    overrides: Partial<FunnelStepWithConversionMetrics> = {}
): Omit<FunnelStepWithConversionMetrics, 'nested_breakdown'> => ({
    action_id: '$pageview',
    average_conversion_time: 0,
    median_conversion_time: 0,
    count: 1,
    name: '$pageview',
    order: 0,
    type: 'events',
    converted_people_url: '',
    dropped_people_url: '',
    droppedOffFromPrevious: 0,
    conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
    ...overrides,
})

const makeStep = (overrides: Partial<FunnelStep> = {}): FunnelStep => ({
    action_id: '$pageview',
    average_conversion_time: 0,
    median_conversion_time: 0,
    count: 1,
    name: '$pageview',
    order: 0,
    type: 'events',
    converted_people_url: '',
    dropped_people_url: '',
    ...overrides,
})

describe('funnelPersonsModalLogic', () => {
    let logic: ReturnType<typeof funnelPersonsModalLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': {
                    results: [{}],
                },
            },
        })
        initKeaTests(false)
    })

    const defaultProps: InsightLogicProps = {
        dashboardItemId: undefined,
        cachedInsight: {
            short_id: undefined,
            query: {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.FunnelsQuery,
                    series: [
                        { kind: NodeKind.ActionsNode, id: 1 },
                        { kind: NodeKind.ActionsNode, id: 1 },
                    ],
                },
            } as InsightVizNode,
            result: null,
        },
    }

    async function initFunnelPersonsModalLogic(props: InsightLogicProps = defaultProps): Promise<void> {
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
        logic = funnelPersonsModalLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    describe('it opens the PersonsModal', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(async () => {
            await initFunnelPersonsModalLogic(props)
            await expectLogic().toDispatchActions(preflightLogic, ['loadPreflightSuccess'])
            await expectLogic(() => {
                router.actions.push(urls.insightEdit(Insight123))
            })
        })

        test('openPersonsModalForStep calls openPersonsModal', async () => {
            logic.actions.openPersonsModalForStep({
                step: makeStep({
                    // Breakdown must be ignored in openPersonsModalForStep
                    converted_people_url: '/some/people/url?funnel_step=2&funnel_step_breakdown=USA',
                    dropped_people_url: '/some/people/url?funnel_step=-2&funnel_step_breakdown=USA',
                }),
                converted: true,
            })

            expect(openPersonsModal).toHaveBeenCalledWith(
                expect.objectContaining({
                    title: expect.anything(),
                    query: expect.objectContaining({ kind: 'FunnelsActorsQuery', funnelStep: 1 }),
                })
            )
        })

        test('openPersonsModalForSeries calls openPersonsModal', async () => {
            logic.actions.openPersonsModalForSeries({
                series: makeSeries({
                    // Breakdown must be ignored in openPersonsModalForStep
                    converted_people_url: '/some/people/url?funnel_step=2&funnel_step_breakdown=Latvia',
                    dropped_people_url: '/some/people/url?funnel_step=-2&funnel_step_breakdown=Latvia',
                }),
                step: makeStep({
                    converted_people_url: '/some/people/url?funnel_step=2&funnel_step_breakdown=USA',
                    dropped_people_url: '/some/people/url?funnel_step=-2&funnel_step_breakdown=USA',
                }),
                converted: true,
            })

            expect(openPersonsModal).toHaveBeenCalledWith(
                expect.objectContaining({
                    title: expect.any(Object),
                    query: expect.objectContaining({ kind: 'FunnelsActorsQuery', funnelStep: 1 }),
                })
            )
        })

        test('openPersonsModalForSeries forwards the previous-period compare label', async () => {
            logic.actions.openPersonsModalForSeries({
                series: makeSeries({ order: 1, compare_label: 'previous' }),
                step: makeStep({ order: 1 }),
                converted: true,
            })

            expect(openPersonsModal).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ kind: 'FunnelsActorsQuery', compare: 'previous' }),
                })
            )
        })

        test('openPersonsModalForSeries forwards the current-period compare label', async () => {
            logic.actions.openPersonsModalForSeries({
                series: makeSeries({ order: 1, compare_label: 'current' }),
                step: makeStep({ order: 1 }),
                converted: true,
            })

            expect(openPersonsModal).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ kind: 'FunnelsActorsQuery', compare: 'current' }),
                })
            )
        })

        test('openPersonsModalForSeries omits compare for a non-compare funnel', async () => {
            logic.actions.openPersonsModalForSeries({
                series: makeSeries({ order: 1 }),
                step: makeStep({ order: 1 }),
                converted: true,
            })

            const { query } = (openPersonsModal as jest.Mock).mock.calls[0][0]
            expect(query.compare).toBeUndefined()
        })
    })

    describe('it never opens the modal for a first-step drop-off', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(async () => {
            await initFunnelPersonsModalLogic(props)
            await expectLogic().toDispatchActions(preflightLogic, ['loadPreflightSuccess'])
            await expectLogic(() => {
                router.actions.push(urls.insightEdit(Insight123))
            })
        })

        // There is no "dropped off before step 1": funnelStep would be -1, which the backend rejects
        // with a ValueError. No UI exposes a first-step drop-off, but the listener guards against an
        // invalid call defensively, so these must no-op rather than fire a query.
        test('openPersonsModalForSeries no-ops on the first step drop-off', async () => {
            logic.actions.openPersonsModalForSeries({
                series: makeSeries({ order: 0, compare_label: 'current' }),
                step: makeStep({ order: 0 }),
                converted: false,
            })

            expect(openPersonsModal).not.toHaveBeenCalled()
        })

        test('openPersonsModalForStep no-ops on the first step drop-off', async () => {
            logic.actions.openPersonsModalForStep({
                step: makeStep({ order: 0 }),
                converted: false,
            })

            expect(openPersonsModal).not.toHaveBeenCalled()
        })

        // The guard must only suppress step 1; a genuine drop-off (step 2+) still opens with funnelStep -2.
        test('a later-step drop-off still opens with a negative funnelStep', async () => {
            logic.actions.openPersonsModalForSeries({
                series: makeSeries({ order: 1, compare_label: 'previous' }),
                step: makeStep({ order: 1 }),
                converted: false,
            })

            expect(openPersonsModal).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ kind: 'FunnelsActorsQuery', funnelStep: -2, compare: 'previous' }),
                })
            )
        })
    })
})
