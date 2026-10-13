/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SignalReportRefundSummaryResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxUsageLogic } from './inboxUsageLogic'

const CREDITS_PER_PR = 1500

const mockUsageEndpoints = (
    currentUsage: number,
    summary: Omit<SignalReportRefundSummaryResponseApi, 'credited_refund_count' | 'quota_limited'> &
        Partial<Pick<SignalReportRefundSummaryResponseApi, 'quota_limited'>>,
    usageLimit?: number
): void => {
    useMocks({
        get: {
            '/api/billing': () => [
                200,
                {
                    products: [
                        {
                            type: 'inbox',
                            display_divisor: CREDITS_PER_PR,
                            current_usage: currentUsage,
                            usage_limit: usageLimit,
                        },
                    ],
                },
            ],
            '/api/projects/:team_id/signals/reports/refund-summary/': () => [
                200,
                { credited_refund_count: summary.credited_credits / CREDITS_PER_PR, quota_limited: false, ...summary },
            ],
        },
    })
}

// $0.01 per credit after a free first tier: 3 free PRs, then $15 per PR.
const PRICED_INBOX_PRODUCT = {
    type: 'inbox',
    subscribed: true,
    display_divisor: CREDITS_PER_PR,
    current_usage: 3 * CREDITS_PER_PR,
    tiers: [
        { unit_amount_usd: '0', up_to: 3 * CREDITS_PER_PR },
        { unit_amount_usd: '0.01', up_to: null },
    ],
}

const mountPricedForSave = async (saveStatus: number): Promise<ReturnType<typeof inboxUsageLogic.build>> => {
    useMocks({
        get: {
            '/api/billing': () => [200, { products: [PRICED_INBOX_PRODUCT] }],
            '/api/projects/:team_id/signals/reports/refund-summary/': () => [
                200,
                { period_billable_credits: 0, credited_credits: 0, credited_refund_count: 0, quota_limited: false },
            ],
        },
        patch: {
            '/api/billing': () =>
                saveStatus === 200
                    ? [200, { products: [PRICED_INBOX_PRODUCT], custom_limits_usd: { inbox: 75 } }]
                    : [saveStatus, { attr: 'custom_limits_usd', detail: 'Rejected.' }],
        },
    })
    featureFlagLogic.mount()
    setRefundsFlag()
    const logic = inboxUsageLogic()
    logic.mount()
    await expectLogic(logic).toFinishAllListeners()
    return logic
}

const setRefundsFlag = (): void => {
    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SIGNALS_PR_REFUNDS], {
        [FEATURE_FLAGS.SIGNALS_PR_REFUNDS]: true,
    })
}

const mountWithUsage = async (
    currentUsage: number,
    summary: Omit<SignalReportRefundSummaryResponseApi, 'credited_refund_count' | 'quota_limited'> &
        Partial<Pick<SignalReportRefundSummaryResponseApi, 'quota_limited'>>,
    usageLimit?: number
): Promise<ReturnType<typeof inboxUsageLogic.build>> => {
    mockUsageEndpoints(currentUsage, summary, usageLimit)
    featureFlagLogic.mount()
    setRefundsFlag()
    const logic = inboxUsageLogic()
    logic.mount()
    await expectLogic(logic).toFinishAllListeners()
    return logic
}

describe('inboxUsageLogic', () => {
    let logic: ReturnType<typeof inboxUsageLogic.build> | undefined

    beforeEach(() => {
        // featureFlagLogic persists to localStorage, which jsdom keeps across tests — without
        // clearing, a flag set in one test leaks into the next test's mount-time state.
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // createdPrs must read `max(billing's recorded usage, live billable credits)`, the gross total
    // the billing page shows: recorded usage lags up to a day, so a just-created PR (and its same-day
    // excluded-path refund) is only visible through the live count. usedPrs must subtract credited
    // refunds, because the quota check does, so a refund frees a slot. Each row pins one side of that
    // contract.
    it.each([
        // [case, billing current_usage, live period credits, credited credits, created, refunded, used]
        ['counts a just-created PR that billing has not recorded yet', 1500, 3000, 0, 2, 0, 2],
        ['drops when a same-day refund removes the PR from live usage', 1500, 1500, 0, 1, 0, 1],
        ['nets credited-path refunds out of the limit count', 9000, 9000, 1500, 6, 1, 5],
        ['clamps at zero when credited refunds exceed billed usage', 0, 1500, 3000, 1, 2, 0],
    ])(
        '%s',
        async (
            _case,
            currentUsage,
            periodBillableCredits,
            creditedCredits,
            expectedCreatedPrs,
            expectedRefundedPrs,
            expectedUsedPrs
        ) => {
            logic = await mountWithUsage(currentUsage, {
                period_billable_credits: periodBillableCredits,
                credited_credits: creditedCredits,
            })

            expect(logic.values).toMatchObject({
                createdPrs: expectedCreatedPrs,
                refundedPrs: expectedRefundedPrs,
                usedPrs: expectedUsedPrs,
            })
        }
    )

    // The quota cron reacts after the fact, so usage runs past the limit before agents pause. The
    // widget must report that overshoot instead of capping it at the limit.
    it('reports usage past the limit instead of capping it', async () => {
        logic = await mountWithUsage(
            53 * CREDITS_PER_PR,
            { period_billable_credits: 53 * CREDITS_PER_PR, credited_credits: 0 },
            50 * CREDITS_PER_PR
        )

        expect(logic.values.usedPrs).toBe(53)
        expect(logic.values.limitPrs).toBe(50)
        expect(logic.values.status).toBe('limit')
    })

    // The refunds flag is keyed on the organization group, so on a fresh pageload it resolves
    // only after mount (once posthog-js registers the group and re-fetches flags). A mount-time
    // load alone would skip the summary forever, pinning the widget to billing's lagging
    // recorded usage until an unrelated archive re-triggered the loader.
    it('loads the refund summary when the flag arrives after mount', async () => {
        mockUsageEndpoints(1500, { period_billable_credits: 6000, credited_credits: 0 })
        featureFlagLogic.mount()
        logic = inboxUsageLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.refundSummary).toBeNull()
        expect(logic.values.usedPrs).toBe(1)

        setRefundsFlag()
        await expectLogic(logic).toDispatchActions(['loadRefundSummary'])
        // The already-rendered card must not collapse into a skeleton while the late-triggered
        // summary load is in flight — the count updates in place once it lands.
        expect(logic.values.isLoading).toBe(false)
        await expectLogic(logic).toDispatchActions(['loadRefundSummarySuccess'])

        expect(logic.values.usedPrs).toBe(4)
    })

    // The enforcement flag and the refunds flag roll out independently; an enforcement-only org
    // still needs the summary loaded, or quota_limited never reaches the paused banner.
    it('loads the summary and surfaces quotaLimited with only the enforcement flag on', async () => {
        mockUsageEndpoints(1500, { period_billable_credits: 1500, credited_credits: 0, quota_limited: true })
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SELF_DRIVING_QUOTA_ENFORCEMENT], {
            [FEATURE_FLAGS.SELF_DRIVING_QUOTA_ENFORCEMENT]: true,
        })
        logic = inboxUsageLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRefundSummarySuccess'])
        expect(logic.values.quotaLimited).toBe(true)
    })

    // A rejected save that closes the modal reads as a saved limit while the agents stay paused.
    it.each([
        ['closes the modal and reloads the paused state when the save lands', 200, false, ['loadRefundSummary']],
        ['keeps the modal open when billing rejects the save', 400, true, []],
    ])('%s', async (_case, saveStatus, expectedModalOpen, expectedFollowUps) => {
        logic = await mountPricedForSave(saveStatus)
        logic.actions.openModal()
        logic.actions.setLimitFormValue('prs', 8)

        await expectLogic(logic, () => logic?.actions.submitLimitForm())
            .toDispatchActions([...expectedFollowUps, 'submitLimitFormSuccess'])
            .toFinishAllListeners()

        expect(logic.values.isModalOpen).toBe(expectedModalOpen)
    })

    it('rejects a PR limit whose dollar cap is above the billing ceiling', async () => {
        logic = await mountPricedForSave(200)
        logic.actions.openModal()

        logic.actions.setLimitFormValue('prs', 3336)
        expect(logic.values.limitFormValidationErrors.prs).toBeUndefined()

        logic.actions.setLimitFormValue('prs', 3337)
        expect(logic.values.limitFormValidationErrors.prs).toBe('Maximum is 3,336 PRs')
    })

    // The org-keyed refunds flag resolves late on the client, so the client can fire the summary
    // request while the server (re-checking the same flag) still returns 404. That mismatch must
    // degrade to a null summary — falling back to billing's own usage — not bubble up as an
    // uncaught error into error tracking.
    it('degrades to null when the server returns 404 for the refund summary', async () => {
        useMocks({
            get: {
                '/api/billing': () => [
                    200,
                    { products: [{ type: 'inbox', display_divisor: CREDITS_PER_PR, current_usage: 1500 }] },
                ],
                '/api/projects/:team_id/signals/reports/refund-summary/': () => [
                    404,
                    { detail: 'PR refunds are not enabled for this organization.' },
                ],
                '/api/projects/:team_id/signals/config/': () => [
                    200,
                    { id: 'cfg-1', default_autostart_priority: 'P4' },
                ],
            },
        })
        featureFlagLogic.mount()
        setRefundsFlag()
        logic = inboxUsageLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadRefundSummarySuccess']).toFinishAllListeners()
        expect(logic.values.refundSummary).toBeNull()
        // Widget still renders from billing's recorded usage rather than tearing down. Billing loads
        // via afterMount independently of the refund summary, so wait for all loaders above before
        // reading usedPrs, which depends on both.
        expect(logic.values.usedPrs).toBe(1)
    })
})
