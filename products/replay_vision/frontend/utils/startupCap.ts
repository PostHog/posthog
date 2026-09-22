import {
    REPLAY_VISION_PRODUCT_KEY,
    STARTUP_PROGRAM_BILLING_LIMIT_MAX_BY_PRODUCT,
} from 'scenes/billing/billingLimitConfig'

import type { BillingType } from '~/types'

import type { VisionQuotaApi } from '../generated/api.schemas'
import { CREDITS_PER_DOLLAR } from './credits'

const STARTUP_PROGRAM_BILLING_LIMIT_MAX = STARTUP_PROGRAM_BILLING_LIMIT_MAX_BY_PRODUCT[REPLAY_VISION_PRODUCT_KEY]

/** Billing enforces this same ceiling server-side, in dollars. */
export const STARTUP_CAP_CREDITS: number = STARTUP_PROGRAM_BILLING_LIMIT_MAX * CREDITS_PER_DOLLAR

export const STARTUP_CAP_EXPLANATION = `Startup credits are shared across all PostHog products, so the startup program caps Replay vision spend at $${STARTUP_PROGRAM_BILLING_LIMIT_MAX.toLocaleString()} per month.`

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
        // Only a real server-side limit can exhaust; the cap is advisory until billing clamps it.
        exhausted: quota.credit_limit !== null && quota.credits_used >= capped,
    }
}
