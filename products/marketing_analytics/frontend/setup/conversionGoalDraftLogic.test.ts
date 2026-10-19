import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type {
    ConversionGoalPreviewApi,
    ConversionGoalPreviewResponseApi,
    ConversionGoalsListResponseApi,
} from '../generated/api.schemas'
import { conversionGoalDraftLogic } from './conversionGoalDraftLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    marketingAnalyticsConversionGoalsPreviewCreate: jest.fn(),
    marketingAnalyticsConversionGoalsRetrieve: jest.fn(),
    marketingAnalyticsConversionGoalsApplyCreate: jest.fn(),
}))

const request: ConversionGoalPreviewApi = {
    goal: {
        kind: 'EventsNode',
        event: 'order_settled',
        conversion_goal_id: '',
        conversion_goal_name: 'Settled orders',
        schema_map: {},
        math: 'sum',
        math_property: 'value',
        counts_as_revenue: true,
    },
    date_from: '2026-01-01T00:00:00Z',
    date_to: '2026-01-14T23:59:59Z',
    filter_test_accounts: true,
}
const result: ConversionGoalPreviewResponseApi = {
    preview_ref: '01800000-0000-4000-8000-000000000001',
    expires_at: '2099-01-15T00:15:00Z',
    goal: { ...request.goal, conversion_goal_id: '__preview__' },
    observed_at: '2026-01-15T00:00:00Z',
    date_from: request.date_from,
    date_to: request.date_to,
    timezone: 'UTC',
    attribution_window_days: 30,
    allows_multiple_conversions_per_visitor: true,
    filter_test_accounts: true,
    exclude_direct_traffic: false,
    exclude_unattributed: false,
    total_conversions: 4,
    evaluated_conversions: 4,
    attributed_conversions: 3,
    unattributed_conversions: 1,
    total_value: 80,
    evaluated_value: 80,
    attributed_value: 60,
    unattributed_value: 20,
    currency: 'EUR',
    conversion_limit_reached: false,
    touchpoint_limit_reached: false,
    is_approximate: false,
    warnings: [],
    checks_not_performed: ['business_definition_validation'],
}
const empty: ConversionGoalsListResponseApi = {
    goals: [],
    conversion_goals: [],
    attribution_window_days: 30,
    attribution_mode: 'last_touch',
    has_misconfigured: false,
    filter_test_accounts: true,
    base_currency: 'EUR',
}

describe('conversionGoalDraftLogic', () => {
    let logic: ReturnType<typeof conversionGoalDraftLogic.build>
    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/marketing_analytics/setup_plan/': { suggestions: [] } } })
        initKeaTests()
        jest.clearAllMocks()
        jest.mocked(api.marketingAnalyticsConversionGoalsPreviewCreate).mockResolvedValue(result)
        jest.mocked(api.marketingAnalyticsConversionGoalsRetrieve).mockResolvedValue(empty)
        logic = conversionGoalDraftLogic({ projectId: 17 })
        logic.mount()
    })
    afterEach(() => logic.unmount())

    async function review(): Promise<void> {
        await expectLogic(logic, () => {
            logic.actions.receiveDraft(request)
            logic.actions.reviewPendingDraft()
        }).toFinishAllListeners()
    }

    it('invalidates the preview and confirmation after edits, and does not replace edits with incoming AI drafts', async () => {
        await review()
        logic.actions.confirmDefinition(true)
        logic.actions.editGoal({ ...logic.values.draft!.goal, math_property: 'net_value' })
        logic.actions.receiveDraft(request)
        await expectLogic(logic, () => logic.actions.saveDraft()).toFinishAllListeners()
        expect(logic.values.draft!.goal.math_property).toBe('net_value')
        expect(logic.values.preview).toBeNull()
        expect(logic.values.definitionConfirmed).toBe(false)
        expect(api.marketingAnalyticsConversionGoalsApplyCreate).not.toHaveBeenCalled()
    })

    it('shows actionable backend validation errors for a preview', async () => {
        jest.mocked(api.marketingAnalyticsConversionGoalsPreviewCreate).mockRejectedValue(
            new ApiError('Invalid goal', 400, undefined, {
                detail: 'Use sum math and select an amount property for revenue.',
            })
        )
        await review()
        expect(logic.values.error).toContain('select an amount property')
        expect(logic.values.preview).toBeNull()
    })

    it('ignores a preview that completes after the draft changes and keeps projects isolated', async () => {
        let resolve: (value: ConversionGoalPreviewResponseApi) => void = () => {}
        jest.mocked(api.marketingAnalyticsConversionGoalsPreviewCreate).mockReturnValueOnce(
            new Promise((done) => {
                resolve = done
            })
        )
        logic.actions.receiveDraft(request)
        logic.actions.reviewPendingDraft()
        logic.actions.editGoal({ ...request.goal, event: 'other_event' })
        resolve(result)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.preview).toBeNull()
        const other = conversionGoalDraftLogic({ projectId: 18 })
        other.mount()
        expect(other.values.draft).toBeNull()
        other.unmount()
    })

    it('serializes saves, checks existing names, and verifies an ambiguous response before permitting another write', async () => {
        await review()
        logic.actions.confirmDefinition(true)
        const savedGoal = {
            ...result.goal,
            conversion_goal_id: 'saved-goal',
            name: result.goal.conversion_goal_name,
        }
        jest.mocked(api.marketingAnalyticsConversionGoalsApplyCreate).mockRejectedValueOnce(
            new Error('Connection lost')
        )
        jest.mocked(api.marketingAnalyticsConversionGoalsRetrieve)
            .mockResolvedValueOnce(empty)
            .mockRejectedValueOnce(new Error('Offline'))
        await expectLogic(logic, () => {
            logic.actions.saveDraft()
            logic.actions.saveDraft()
        }).toFinishAllListeners()
        expect(api.marketingAnalyticsConversionGoalsApplyCreate).toHaveBeenCalledTimes(2)
        expect(logic.values.saveStatus).toBe('unknown')
        logic.actions.editGoal({ ...result.goal, math_property: 'different_amount' })
        expect(logic.values.preview?.goal.math_property).toBe(result.goal.math_property)
        await expectLogic(logic, () => logic.actions.saveDraft()).toFinishAllListeners()
        expect(api.marketingAnalyticsConversionGoalsApplyCreate).toHaveBeenCalledTimes(2)
        jest.mocked(api.marketingAnalyticsConversionGoalsRetrieve).mockResolvedValue({
            ...empty,
            conversion_goals: [savedGoal],
        })
        await expectLogic(logic, () => logic.actions.verifySave()).toFinishAllListeners()
        expect(logic.values.saveStatus).toBe('saved')
        expect(api.marketingAnalyticsConversionGoalsApplyCreate).toHaveBeenCalledTimes(3)
        for (const [, payload] of jest.mocked(api.marketingAnalyticsConversionGoalsApplyCreate).mock.calls) {
            expect(payload.preview_ref).toBe(result.preview_ref)
        }
    })

    it('does not apply a new unconfirmed draft when an old save completes after remount', async () => {
        await review()
        logic.actions.confirmDefinition(true)
        let completeSave: () => void = () => {}
        let writeStarted: () => void = () => {}
        const started = new Promise<void>((resolve) => {
            writeStarted = resolve
        })
        jest.mocked(api.marketingAnalyticsConversionGoalsApplyCreate).mockImplementationOnce(async () => {
            writeStarted()
            await new Promise<void>((resolve) => {
                completeSave = resolve
            })
            return { goal: result.goal, conversion_goals: [result.goal] }
        })
        logic.actions.saveDraft()
        await started
        const oldLogic = logic
        logic.unmount()
        logic = conversionGoalDraftLogic({ projectId: 17 })
        logic.mount()
        const other = {
            ...request,
            goal: { ...request.goal, event: 'another_order', conversion_goal_name: 'Another order' },
        }
        jest.mocked(api.marketingAnalyticsConversionGoalsPreviewCreate).mockResolvedValue({
            ...result,
            goal: other.goal,
            preview_ref: '01800000-0000-4000-8000-000000000002',
        })
        await expectLogic(logic, () => {
            logic.actions.receiveDraft(other)
            logic.actions.reviewPendingDraft()
        }).toDispatchActions(['previewReceived'])
        completeSave()
        await expectLogic(oldLogic).toFinishAllListeners()
        expect(logic.values.definitionConfirmed).toBe(false)
        expect(logic.values.saveStatus).toBe('idle')
        expect(logic.values.preview?.goal).toMatchObject({ event: 'another_order' })
        expect(api.marketingAnalyticsConversionGoalsApplyCreate).toHaveBeenCalledTimes(1)
    })

    it.each(['existing_name', 'mismatched_saved_definition'])(
        'does not accept %s as a successful save',
        async (scenario) => {
            await review()
            logic.actions.confirmDefinition(true)
            const conflicting = { ...result.goal, conversion_goal_id: 'different', math_property: 'other_value' }
            if (scenario === 'existing_name') {
                jest.mocked(api.marketingAnalyticsConversionGoalsRetrieve).mockResolvedValue({
                    ...empty,
                    conversion_goals: [conflicting],
                })
            } else {
                jest.mocked(api.marketingAnalyticsConversionGoalsApplyCreate).mockResolvedValue({
                    goal: result.goal,
                    conversion_goals: [result.goal],
                })
                jest.mocked(api.marketingAnalyticsConversionGoalsRetrieve)
                    .mockResolvedValueOnce(empty)
                    .mockResolvedValue({ ...empty, conversion_goals: [conflicting] })
            }
            await expectLogic(logic, () => logic.actions.saveDraft()).toFinishAllListeners()
            expect(logic.values.saveStatus).not.toBe('saved')
            expect(logic.values.error).toBeTruthy()
            expect(api.marketingAnalyticsConversionGoalsApplyCreate).toHaveBeenCalledTimes(
                scenario === 'existing_name' ? 0 : 2
            )
        }
    )
})
