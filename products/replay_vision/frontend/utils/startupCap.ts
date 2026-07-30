import { STARTUP_PROGRAM_BILLING_LIMIT_MAX } from 'scenes/billing/billingLimitConfig'

import type { BillingType } from '~/types'

import type { VisionQuotaApi } from '../generated/api.schemas'
import { CREDITS_PER_DOLLAR } from './credits'

/** Billing enforces this same ceiling server-side, in dollars. */
export const STARTUP_CAP_CREDITS: number = STARTUP_PROGRAM_BILLING_LIMIT_MAX * CREDITS_PER_DOLLAR

export const STARTUP_CAP_EXPLANATION = `The startup program caps Replay vision spend at $${STARTUP_PROGRAM_BILLING_LIMIT_MAX.toLocaleString()} per month, so credits can't all go to Replay vision at once.`

export function startupCapCredits(billing: BillingType | null): number | null {
    return billing?.startup_program_label ? STARTUP_CAP_CREDITS : null
}

/** Display only: billing clamps the stored limit to the same cap, so this just covers orgs it hasn't reached yet. */
export function applyStartupCap(quota: VisionQuotaApi | null, capCredits: number | null): VisionQuotaApi | null {
    if (!quota || capCredits === null) {
        return quota
    }
    const capped = quota.credit_limit === null ? capCredits : Math.min(quota.credit_limit, capCredits)
    if (capped === quota.credit_limit) {
        return quota
    }
    return {
        ...quota,
        credit_limit: capped,
        remaining: Math.max(capped - quota.credits_used, 0),
        // Without this the meter can read over 100% while the status line still says "on track".
        exhausted: quota.credits_used >= capped,
    }
}
