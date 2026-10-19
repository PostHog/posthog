import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, PropertyMathType, TeamType } from '~/types'

import type { ConversionRecommendationApi } from '../generated/api.schemas'
import { conversionGoalFormLogic } from './conversionGoalFormLogic'
import { recommendationToGoal } from './recommendationToGoal'

const recommendation: ConversionRecommendationApi = {
    source_ref: 'event:order_settled',
    name: 'Settled orders',
    reason: 'This event may record completed payments.',
    intent: 'revenue',
    amount_property: 'order_value',
    questions: ['Does this exclude refunds and duplicate transactions?'],
    candidate: {
        source_ref: 'event:order_settled',
        name: 'order_settled',
        kind: 'EventsNode',
        event: 'order_settled',
        numeric_properties: ['order_value'],
    },
}

describe('conversion goal drafts', () => {
    beforeEach(() => {
        useMocks({})
        initKeaTests()
    })

    it.each([
        [
            recommendation,
            {
                kind: NodeKind.EventsNode,
                event: 'order_settled',
                math: PropertyMathType.Sum,
                math_property: 'order_value',
                counts_as_revenue: true,
                counts_as_customer: false,
            },
        ],
        [
            {
                ...recommendation,
                intent: 'customer',
                amount_property: null,
                candidate: { source_ref: 'action:42', kind: 'ActionsNode', action_id: 42, name: 'Qualified requests' },
            },
            {
                kind: NodeKind.ActionsNode,
                id: 42,
                math: BaseMathType.TotalCount,
                counts_as_revenue: false,
                counts_as_customer: true,
            },
        ],
        [
            { ...recommendation, intent: 'conversion', amount_property: null },
            { math: BaseMathType.TotalCount, counts_as_revenue: false, counts_as_customer: false },
        ],
    ] as const)('preserves the source and measurement for %j', (suggestion, expected) => {
        const goal = recommendationToGoal(suggestion)
        expect(goal).toMatchObject(expected)
        if (goal.kind === NodeKind.ActionsNode) {
            expect(goal).not.toHaveProperty('event')
        }
    })

    it('prefills without saving, submits only once, and preserves a failed draft for retry', async () => {
        const logic = conversionGoalFormLogic({ projectId: teamLogic.values.currentTeamId! })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const originalGoals = marketingAnalyticsSettingsLogic.values.conversion_goals
        let release!: () => void
        let responseReady = new Promise<void>((resolve) => {
            release = resolve
        })
        let status = 500
        const writes: Partial<TeamType>[] = []
        useMocks({
            patch: {
                '/api/environments/:team_id': async ({ request }) => {
                    const payload = (await request.json()) as Partial<TeamType>
                    writes.push(payload)
                    await responseReady
                    return [status, { ...teamLogic.values.currentTeam, ...payload }]
                },
            },
        })

        await expectLogic(logic, () => logic.actions.selectRecommendation(recommendation)).toFinishAllListeners()
        expect(writes).toHaveLength(0)
        expect(marketingAnalyticsSettingsLogic.values.conversion_goals).toEqual(originalGoals)
        expect(logic.values.filter).toMatchObject({ event: 'order_settled', math_property: 'order_value' })
        expect(logic.values.name).toBe('Settled orders')
        expect(logic.values.recommendation?.questions).toEqual(recommendation.questions)

        logic.actions.setName('Reviewed payments')
        logic.actions.saveGoal()
        logic.actions.saveGoal()
        expect(logic.values.isSaving).toBe(true)
        release()
        await expectLogic(teamLogic).toFinishAllListeners()
        expect(writes).toHaveLength(1)
        expect(logic.values.isSaving).toBe(false)
        expect(logic.values.saveError).toBeTruthy()
        expect(logic.values.name).toBe('Reviewed payments')
        const goalId = logic.values.filter.conversion_goal_id
        expect(goalId).toBeTruthy()

        status = 200
        responseReady = Promise.resolve()
        await expectLogic(logic, () => logic.actions.saveGoal()).toFinishAllListeners()
        await expectLogic(teamLogic).toFinishAllListeners()
        expect(writes).toHaveLength(2)
        expect(
            writes[1].marketing_analytics_config?.conversion_goals?.filter((goal) => goal.conversion_goal_id === goalId)
        ).toEqual([
            expect.objectContaining({
                conversion_goal_name: 'Reviewed payments',
                math: PropertyMathType.Sum,
                math_property: 'order_value',
                counts_as_revenue: true,
            }),
        ])
        expect(logic.values.isSaving).toBe(false)
        expect(logic.values.saveError).toBeNull()
        expect(logic.values.isFormValid).toBe(false)
        expect(logic.values.recommendation).toBeNull()
        logic.unmount()
    })

    it('keeps drafts separate and rejects saving a draft for a different project', async () => {
        const projectId = teamLogic.values.currentTeamId!
        const current = conversionGoalFormLogic({ projectId })
        const other = conversionGoalFormLogic({ projectId: projectId + 1 })
        current.mount()
        other.mount()
        await expectLogic(current).toFinishAllListeners()
        current.actions.selectRecommendation(recommendation)
        expect(other.values.isFormValid).toBe(false)
        other.actions.selectRecommendation(recommendation)
        await expectLogic(other, () => other.actions.saveGoal()).toNotHaveDispatchedActions(['saveStarted'])
        expect(other.values.isSaving).toBe(false)
        current.unmount()
        other.unmount()
    })
})
