import { RRule } from 'rrule'

import { SubscriptionType } from '~/types'

const RRULE_WEEKDAY_MAP: Record<string, (typeof RRule)['MO']> = {
    monday: RRule.MO,
    tuesday: RRule.TU,
    wednesday: RRule.WE,
    thursday: RRule.TH,
    friday: RRule.FR,
    saturday: RRule.SA,
    sunday: RRule.SU,
}

const RRULE_FREQ_MAP: Record<string, number> = {
    daily: RRule.DAILY,
    weekly: RRule.WEEKLY,
    monthly: RRule.MONTHLY,
    yearly: RRule.YEARLY,
}

// Client-side preview only — the authoritative next delivery date is computed
// server-side in posthog/models/subscription.py (Subscription.set_next_delivery_date)
export function getNextDeliveryDate(subscription: Partial<SubscriptionType>): Date | null {
    if (!subscription.frequency || !subscription.start_date) {
        return null
    }
    try {
        const rule = new RRule({
            freq: RRULE_FREQ_MAP[subscription.frequency],
            interval: subscription.interval ?? 1,
            dtstart: new Date(subscription.start_date),
            byweekday: subscription.byweekday?.map((d) => RRULE_WEEKDAY_MAP[d]) ?? null,
            bysetpos: subscription.frequency === 'monthly' ? (subscription.bysetpos ?? null) : null,
        })
        return rule.after(new Date())
    } catch {
        return null
    }
}
