import { AlertConditionType } from '~/queries/schema/schema-general'
import type { InsightThresholdType } from '~/queries/schema/schema-general'

import { formatThresholdSummary } from 'products/alerts/frontend/components/alertSummary'
import type { AlertApi } from 'products/alerts/frontend/generated/api.schemas'
import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import type { SentenceFollowUp, SentencePart } from '../sentence/buildSentence'

function subscriptionTarget(subscription: SubscriptionApi, userEmail: string | undefined): string {
    if (subscription.target_type !== 'email') {
        // A channel is stored as its id and its name: "C0123|#growth".
        const channel = subscription.target_value.split('|')[1]
        return channel || (subscription.target_type === 'slack' ? 'Slack' : 'Teams')
    }
    const emails = subscription.target_value
        .split(',')
        .map((email) => email.trim())
        .filter(Boolean)
    if (emails.length === 1) {
        return emails[0] === userEmail ? 'you' : '1 person'
    }
    return `${emails.length} people`
}

function subscriptionFollowUp(
    subscriptions: SubscriptionApi[],
    userEmail: string | undefined
): SentenceFollowUp | null {
    const active = subscriptions.filter((subscription) => !subscription.deleted && subscription.enabled !== false)
    if (!active.length) {
        return null
    }
    if (active.length > 1) {
        return {
            slot: 'subscription',
            opening: 'Sent on ',
            lead: 'sent on ',
            text: `${active.length} schedules`,
            itemId: null,
        }
    }
    const [subscription] = active
    // The API words a schedule as "sent daily". The sentence has its own "sent", so the word starts at the schedule.
    const schedule = subscription.summary.replace(/^sent\s+/i, '')
    return {
        slot: 'subscription',
        opening: 'Sent ',
        lead: 'sent ',
        text: `${schedule} to ${subscriptionTarget(subscription, userEmail)}`,
        itemId: String(subscription.id),
    }
}

function alertFollowUp(alerts: AlertApi[]): SentenceFollowUp | null {
    const active = alerts.filter((alert) => alert.enabled !== false)
    if (!active.length) {
        return null
    }
    if (active.length > 1) {
        return { slot: 'alert', opening: 'Has ', lead: 'with ', text: `${active.length} alerts`, itemId: null }
    }
    const [alert] = active
    const { bounds, type } = alert.threshold.configuration
    return {
        slot: 'alert',
        opening: 'Has an alert for ',
        lead: 'with an alert for ',
        text: alert.detector_config
            ? 'an anomaly'
            : formatThresholdSummary(
                  (alert.condition?.type ?? AlertConditionType.ABSOLUTE_VALUE) as AlertConditionType,
                  type as InsightThresholdType,
                  bounds?.lower ?? undefined,
                  bounds?.upper ?? undefined
              ),
        itemId: alert.id,
    }
}

export function followUpsFrom(
    subscriptions: SubscriptionApi[],
    alerts: AlertApi[],
    userEmail: string | undefined
): SentenceFollowUp[] {
    return [subscriptionFollowUp(subscriptions, userEmail), alertFollowUp(alerts)].filter(
        (followUp): followUp is SentenceFollowUp => !!followUp
    )
}

export function followUpLine(followUps: SentenceFollowUp[]): SentencePart[] {
    if (!followUps.length) {
        return []
    }
    const parts: SentencePart[] = followUps.flatMap((followUp, index) => [
        { type: 'text', text: index === 0 ? followUp.opening : `, ${followUp.lead}` },
        { type: 'value', slot: followUp.slot, text: followUp.text, itemId: followUp.itemId },
    ])
    return [...parts, { type: 'text', text: '.' }]
}
