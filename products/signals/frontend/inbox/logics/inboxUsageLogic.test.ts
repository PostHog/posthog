/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { billingLogic } from 'scenes/billing/billingLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingType } from '~/types'

import type { SignalReportRefundSummaryResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxUsageLogic } from './inboxUsageLogic'

const CREDITS_PER_PR = 1500

const mockUsageEndpoints = (
    currentUsage: number,
    summary: Omit<SignalReportRefundSummaryResponseApi, 'credited_refund_count' | 'quota_limited'> &
        Partial<Pick<SignalReportRefundSummaryResponseApi, 'quota_limited'>>
): void => {
    useMocks({
        get: {
            '/api/billing': () => [
                200,
                { products: [{ type: 'inbox', display_divisor: CREDITS_PER_PR, current_usage: currentUsage }] },
            ],
            '/api/projects/:team_id/signals/reports/refund-summary/': () => [
                200,
                { credited_refund_count: summary.credited_credits / CREDITS_PER_PR, quota_limited: false, ...summary },
            ],
        },
    })
}

const setRefundsFlag = (): void => {
    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SIGNALS_PR_REFUNDS], {
        [FEATURE_FLAGS.SIGNALS_PR_REFUNDS]: true,
    })
}

const mountWithUsage = async (
    currentUsage: number,
    summary: Omit<SignalReportRefundSummaryResponseApi, 'credited_refund_count' | 'quota_limited'> &
        Partial<Pick<SignalReportRefundSummaryResponseApi, 'quota_limited'>>
): Promise<ReturnType<typeof inboxUsageLogic.build>> => {
    mockUsageEndpoints(currentUsage, summary)
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

    // usedPrs must read `max(billing's recorded usage, live billable credits) − credited refunds`:
    // recorded usage lags up to a day, so a just-created PR (and its same-day excluded-path refund)
    // is only visible through the live count, while credited-path refunds stay in recorded usage
    // and must be netted out. Each row pins one side of that contract.
    it.each([
        // [case, billing current_usage, live period credits, credited credits, expected PRs]
        ['counts a just-created PR that billing has not recorded yet', 1500, 3000, 0, 2],
        ['drops when a same-day refund removes the PR from live usage', 1500, 1500, 0, 1],
        ['nets credited-path refunds out of recorded usage', 9000, 9000, 1500, 5],
        ['clamps at zero when credited refunds exceed billed usage', 0, 1500, 3000, 0],
    ])('%s', async (_case, currentUsage, periodBillableCredits, creditedCredits, expectedPrs) => {
        logic = await mountWithUsage(currentUsage, {
            period_billable_credits: periodBillableCredits,
            credited_credits: creditedCredits,
        })

        expect(logic.values.usedPrs).toBe(expectedPrs)
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

    // A limit lowered below current usage takes effect next period; billing records it under
    // `next_period_custom_limits_usd`, not `custom_limits_usd`. The widget must read it and price it
    // back into PRs, otherwise the lowered limit reads as a silent revert.
    it('reads next_period_custom_limits_usd as a pending PR limit', async () => {
        useMocks({
            get: {
                '/api/billing': () => [
                    200,
                    {
                        products: [
                            {
                                type: 'inbox',
                                display_divisor: CREDITS_PER_PR,
                                unit_amount_usd: '0.01',
                                current_usage: 0,
                            },
                        ],
                        next_period_custom_limits_usd: { inbox: 150 },
                    },
                ],
                '/api/projects/:team_id/signals/reports/refund-summary/': () => [
                    200,
                    { credited_refund_count: 0, quota_limited: false, period_billable_credits: 0, credited_credits: 0 },
                ],
            },
        })
        featureFlagLogic.mount()
        setRefundsFlag()
        logic = inboxUsageLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // 0.01 USD/credit × 1500 credits = 15 USD/PR; 150 USD / 15 = 10 PRs, with no free tier.
        expect(logic.values.pricePerPrUsd).toBe(15)
        expect(logic.values.nextPeriodLimitPrs).toBe(10)
    })

    // The submit only fires the billing update. The modal must close on that write landing (so a
    // failed write keeps it open with the error), and the refund summary must reload so a raised
    // limit clears the paused banner in place.
    it('closes the modal and reloads the refund summary when a limit update lands', async () => {
        logic = await mountWithUsage(1500, { period_billable_credits: 1500, credited_credits: 0 })
        logic.actions.openModal()
        expect(logic.values.isModalOpen).toBe(true)

        await expectLogic(logic, () => {
            billingLogic.actions.updateBillingLimitsSuccess({ products: [] } as unknown as BillingType)
        }).toDispatchActions(['loadRefundSummary'])
        expect(logic.values.isModalOpen).toBe(false)
    })

    // The Save button is disabled during a write, but the focused input still submits on Enter. A
    // second submit while the first PATCH is in flight must not fire a duplicate limit write — the
    // submit handler bails while billingLoading is true.
    it('does not fire a second limit write while the first is in flight', async () => {
        let releasePatch = (): void => {}
        const patchGate = new Promise<void>((resolve) => {
            releasePatch = resolve
        })
        const inboxProduct = {
            type: 'inbox',
            display_divisor: CREDITS_PER_PR,
            unit_amount_usd: '0.01',
            current_usage: 0,
        }
        useMocks({
            get: {
                '/api/billing': () => [200, { products: [inboxProduct] }],
                '/api/projects/:team_id/signals/reports/refund-summary/': () => [
                    200,
                    { credited_refund_count: 0, quota_limited: false, period_billable_credits: 0, credited_credits: 0 },
                ],
            },
            patch: {
                '/api/billing': async () => {
                    await patchGate
                    return [200, { products: [inboxProduct], custom_limits_usd: { inbox: 150 } }]
                },
            },
        })
        featureFlagLogic.mount()
        setRefundsFlag()
        logic = inboxUsageLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openModal()
        logic.actions.setLimitFormValue('prs', 10)

        // First submit starts the write and holds billingLoading true until the gated PATCH resolves.
        await expectLogic(logic, () => {
            logic!.actions.submitLimitForm()
        })
            .toDispatchActions(['updateBillingLimits'])
            .toMatchValues({ billingLoading: true })

        // Second submit while loading completes but must not dispatch a duplicate updateBillingLimits.
        await expectLogic(logic, () => {
            logic!.actions.submitLimitForm()
        })
            .toDispatchActions(['submitLimitFormSuccess'])
            .toNotHaveDispatchedActions(['updateBillingLimits'])

        // Releasing the PATCH lets the single write land, which closes the modal via the success listener.
        releasePatch()
        await expectLogic(logic).toDispatchActions(['closeModal'])
        expect(logic.values.isModalOpen).toBe(false)
    })
})
