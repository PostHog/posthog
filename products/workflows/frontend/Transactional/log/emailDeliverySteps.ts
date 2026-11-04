import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type {
    EmailLogEventKindEnumApi,
    TransactionalEmailLogDetailApi,
    TransactionalEmailLogEventApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { EMAIL_STATUS_LABEL, emailReasonText } from './emailLogStatus'

export type DeliveryStepState = 'done' | 'failed' | 'pending'

export interface DeliveryStep {
    key: string
    label: string
    state: DeliveryStepState
    at: string | null
    detail: string | null
    previousAt: string | null
}

const FAILURE_KINDS: EmailLogEventKindEnumApi[] = ['bounced', 'complained', 'failed']

function firstOf(
    timeline: readonly TransactionalEmailLogEventApi[],
    kind: EmailLogEventKindEnumApi
): TransactionalEmailLogEventApi | undefined {
    return timeline.find((event) => event.kind === kind)
}

function countOf(timeline: readonly TransactionalEmailLogEventApi[], kind: EmailLogEventKindEnumApi): number {
    return timeline.filter((event) => event.kind === kind).length
}

function step(
    key: string,
    label: string,
    event: { at: string } | undefined,
    previousAt: string | null,
    detail: string | null = null
): DeliveryStep {
    return { key, label, state: event ? 'done' : 'pending', at: event?.at ?? null, detail, previousAt }
}

function repeated(count: number, verb: string): string | null {
    return count > 1 ? `${verb} ${count} times` : null
}

/** The steps an email went through, ending at its first failure. */
export function buildDeliverySteps(email: TransactionalEmailLogDetailApi): DeliveryStep[] {
    const { timeline } = email
    const sent = firstOf(timeline, 'sent')
    const delivered = firstOf(timeline, 'delivered')
    const opened = firstOf(timeline, 'opened')
    const failure = timeline.find((event) => FAILURE_KINDS.includes(event.kind))
    const queuedAt = firstOf(timeline, 'queued')?.at ?? email.created_at
    const stopped = (
        kind: 'failed' | 'bounced' | 'complained',
        previousAt: string | null,
        detail: string | null
    ): DeliveryStep => ({
        key: kind,
        label: EMAIL_STATUS_LABEL[kind],
        state: 'failed',
        at: failure?.at ?? null,
        detail,
        previousAt,
    })
    const reason = emailReasonText(failure?.reason ?? email.reason)
    const queuedStep = step('queued', 'Queued', { at: queuedAt }, null)

    if (email.status === 'failed') {
        return [queuedStep, stopped('failed', queuedAt, reason)]
    }
    // A send that went out shows Sent as its first step. Queued only matters while it waits.
    const lead = sent ? [] : [queuedStep]
    const sentStep = step('sent', 'Sent', sent, lead.length ? queuedAt : null)
    if (email.status === 'bounced') {
        return [...lead, sentStep, stopped('bounced', sent?.at ?? null, reason)]
    }
    // A spam report proves the email arrived, even when the delivery update has not.
    const deliveredStep = step('delivered', 'Delivered', delivered, sent?.at ?? null)
    if (email.status === 'complained') {
        return [
            ...lead,
            sentStep,
            { ...deliveredStep, state: 'done' },
            stopped('complained', delivered?.at ?? sent?.at ?? null, 'The recipient reported this email as spam'),
        ]
    }
    return [
        ...lead,
        sentStep,
        deliveredStep,
        step('opened', 'Opened', opened, delivered?.at ?? null, repeated(countOf(timeline, 'opened'), 'Opened')),
        step(
            'clicked',
            'Clicked',
            firstOf(timeline, 'clicked'),
            opened?.at ?? delivered?.at ?? null,
            repeated(countOf(timeline, 'clicked'), 'Clicked')
        ),
    ]
}

/** "3s later", for the time between a step and the one before it. */
export function gapLabel(at: string, previousAt: string | null): string | null {
    if (!previousAt) {
        return null
    }
    const seconds = dayjs(at).diff(dayjs(previousAt), 'second')
    if (seconds < 1) {
        return 'under a second later'
    }
    return `${humanFriendlyDuration(seconds, { maxUnits: 1 })} later`
}
