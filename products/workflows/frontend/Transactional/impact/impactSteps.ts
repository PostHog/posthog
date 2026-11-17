import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

export type ImpactStepKey = 'sent' | 'delivered' | 'opened' | 'clicked' | 'session' | 'converted'

export interface ImpactStep {
    key: ImpactStepKey
    label: string
    /** Null when the step can't be counted; `missing` says why. */
    value: number | null
    missing?: string
    missingDetail?: string
    /** Share of the step it compares to, from 0 to 1. */
    share: number | null
    /** Names the step `share` compares to, when it isn't the one before. */
    shareOf?: string
}

export interface ImpactLift {
    /** Share of clicked sends whose recipient converted. Null when nobody clicked. */
    clicked: number | null
    /** Share of delivered sends nobody clicked whose recipient converted. Null when there were none. */
    notClicked: number | null
}

export const LINK_TAGGING_DETAIL =
    "PostHog follows a click into your product through a tag on the email's links. Link tagging isn't on for this project yet. Conversions still count, because they go through the person on each send."

const NOT_TRACKED_DETAIL =
    'No opens or clicks were recorded for these sends, so tracking was likely off, as it is for sensitive emails.'

function share(value: number, of: number): number | null {
    return of > 0 ? value / of : null
}

/**
 * Tracking is decided per send and isn't stored, so a run of deliveries with no open and no click is the sign it was
 * off. The email's sensitive setting isn't used: it describes the email today, not the sends being counted.
 */
export function clicksTracked(impact: TransactionalEmailImpactApi): boolean {
    return !(impact.delivered > 0 && impact.opened === 0 && impact.clicked === 0)
}

export function impactSteps(impact: TransactionalEmailImpactApi, event: string | null, tracked: boolean): ImpactStep[] {
    const notTracked = { value: null, share: null, missing: 'Not tracked', missingDetail: NOT_TRACKED_DETAIL }
    const steps: ImpactStep[] = [
        { key: 'sent', label: 'Sent', value: impact.sent, share: null },
        { key: 'delivered', label: 'Delivered', value: impact.delivered, share: share(impact.delivered, impact.sent) },
        tracked
            ? { key: 'opened', label: 'Opened', value: impact.opened, share: share(impact.opened, impact.delivered) }
            : { key: 'opened', label: 'Opened', ...notTracked },
        tracked
            ? { key: 'clicked', label: 'Clicked', value: impact.clicked, share: share(impact.clicked, impact.opened) }
            : { key: 'clicked', label: 'Clicked', ...notTracked },
        tracked
            ? {
                  key: 'session',
                  label: 'Started a session',
                  value: null,
                  share: null,
                  missing: 'Needs link tagging',
                  missingDetail: LINK_TAGGING_DETAIL,
              }
            : { key: 'session', label: 'Started a session', ...notTracked },
    ]
    // Without click tracking every delivered send counts from when it was sent, so the share is of delivered.
    const conversions = tracked ? impact.after_click : impact.without_click
    steps.push(
        event && conversions
            ? {
                  key: 'converted',
                  label: event,
                  value: conversions.converted,
                  share: share(conversions.converted, conversions.sends),
                  shareOf: tracked ? 'clicked' : 'delivered',
              }
            : { key: 'converted', label: 'Converted', value: null, share: null, missing: 'Pick an event' }
    )
    return steps
}

export function impactLift(impact: TransactionalEmailImpactApi): ImpactLift | null {
    if (!impact.after_click || !impact.without_click) {
        return null
    }
    return {
        clicked: share(impact.after_click.converted, impact.after_click.sends),
        notClicked: share(impact.without_click.converted, impact.without_click.sends),
    }
}
