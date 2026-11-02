import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, PropertyFilterType, PropertyMathType, PropertyOperator, TeamType } from '~/types'

import type { ConversionRecommendationApi } from '../generated/api.schemas'
import { conversionGoalFormLogic } from './conversionGoalFormLogic'
import { conversionRecommendationsLogic } from './conversionRecommendationsLogic'
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
        logic.actions.setFilter({ ...logic.values.filter, counts_as_customer: true })
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
                counts_as_customer: true,
            }),
        ])
        expect(logic.values.isSaving).toBe(false)
        expect(logic.values.saveError).toBeNull()
        expect(logic.values.isFormValid).toBe(false)
        expect(logic.values.recommendation).toBeNull()
        expect(logic.values.findExistingGoal(recommendation)?.conversion_goal_id).toBe(goalId)
        const recommendations = conversionRecommendationsLogic({
            projectId: teamLogic.values.currentTeamId!,
            enabled: false,
        })
        recommendations.mount()
        const run = {
            id: 'scan',
            status: 'completed' as const,
            lookback_days: 30,
            date_from: '2026-01-01',
            date_to: '2026-01-31',
            created_at: '2026-01-31',
            completed_at: '2026-01-31',
            error: '',
        }
        recommendations.actions.loadRecommendationsSuccess({
            latest_run: run,
            result_run: run,
            results: { recommendations: [recommendation] },
            can_generate: true,
            generation_disabled_reason: null,
        })
        expect(recommendations.values.pendingRecommendations).toEqual([])
        expect(recommendations.values.allRecommendationsConfigured).toBe(true)
        recommendations.unmount()
        logic.unmount()
    })

    it.each(
        [false, true].flatMap((staleDraft) => [
            { staleDraft, changes: {} },
            { staleDraft, changes: { counts_as_customer: true } },
            { staleDraft, changes: { math: PropertyMathType.Average, counts_as_revenue: false } },
            {
                staleDraft,
                changes: {
                    properties: [
                        {
                            key: 'status',
                            value: 'paid',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event as const,
                        },
                    ],
                },
            },
        ])
    )('reviews a configured source without creating a duplicate: %j', async ({ staleDraft, changes }) => {
        const logic = conversionGoalFormLogic({ projectId: teamLogic.values.currentTeamId! })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const existing = {
            ...recommendationToGoal(recommendation),
            conversion_goal_id: 'saved-payments',
            conversion_goal_name: 'Reviewed payments',
            ...changes,
        }
        const writes: Partial<TeamType>[] = []
        useMocks({
            patch: {
                '/api/environments/:team_id': async ({ request }) => {
                    const payload = (await request.json()) as Partial<TeamType>
                    writes.push(payload)
                    return [200, { ...teamLogic.values.currentTeam, ...payload }]
                },
            },
        })
        if (staleDraft) {
            logic.actions.selectRecommendation(recommendation)
        }
        teamLogic.actions.loadCurrentTeamSuccess({
            ...teamLogic.values.currentTeam!,
            marketing_analytics_config: { conversion_goals: [existing] },
        })
        expect(logic.values.findExistingGoal(recommendation)).toEqual(existing)
        if (staleDraft) {
            logic.actions.saveGoal()
        } else {
            logic.actions.selectRecommendation(recommendation)
        }
        await expectLogic(logic).toFinishAllListeners()
        expect(writes).toHaveLength(0)
        expect(logic.values.filter).toEqual(existing)
        expect(logic.values.name).toBe('Reviewed payments')
        expect(logic.values.editingGoalId).toBe(existing.conversion_goal_id)
        expect(logic.values.duplicateGoal).toBeNull()

        logic.actions.setName('Confirmed payments')
        await expectLogic(logic, () => logic.actions.saveGoal()).toFinishAllListeners()
        await expectLogic(teamLogic).toFinishAllListeners()
        expect(writes).toHaveLength(1)
        expect(writes[0].marketing_analytics_config?.conversion_goals).toEqual([
            { ...existing, conversion_goal_name: 'Confirmed payments' },
        ])
        expect(logic.values.editingGoalId).toBeNull()
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
        expect(other.values.configuredGoals).toEqual([])
        expect(other.values.findExistingGoal(recommendation)).toBeUndefined()
        current.unmount()
        other.unmount()
    })
})
