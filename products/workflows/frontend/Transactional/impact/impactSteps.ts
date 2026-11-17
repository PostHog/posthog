import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

export type ImpactStepKey = 'sent' | 'delivered' | 'opened' | 'clicked' | 'session' | 'converted'

export interface ImpactStep {
    key: ImpactStepKey
    label: string
    value: number | null
    missing?: string
    missingDetail?: string
    share: number | null
    shareOf?: string
    shareDetail?: string
}

export interface ImpactLift {
    clicked: number | null
    notClicked: number | null
}

export const LINK_TAGGING_DETAIL =
    "PostHog follows a click into your product through a tag on the email's links. Link tagging isn't on for this project yet. Conversions still count, because they go through the person on each send."

const NOT_TRACKED_DETAIL =
    'No opens or clicks were recorded for these sends, so tracking was likely off, as it is for sensitive emails.'

function share(value: number, of: number): number | null {
    return of > 0 ? value / of : null
}

export function clicksTracked(impact: TransactionalEmailImpactApi): boolean {
    return !(impact.delivered > 0 && impact.opened === 0 && impact.clicked === 0)
}

export function impactSteps(impact: TransactionalEmailImpactApi, event: string | null): ImpactStep[] {
    const tracked = clicksTracked(impact)
    const notTracked = { value: null, share: null, missing: 'Not tracked', missingDetail: NOT_TRACKED_DETAIL }
    const steps: ImpactStep[] = [
        { key: 'sent', label: 'Sent', value: impact.sent, share: null },
        { key: 'delivered', label: 'Delivered', value: impact.delivered, share: share(impact.delivered, impact.sent) },
        tracked
            ? { key: 'opened', label: 'Opened', value: impact.opened, share: share(impact.opened, impact.delivered) }
            : { key: 'opened', label: 'Opened', ...notTracked },
        tracked ? clickedStep(impact) : { key: 'clicked', label: 'Clicked', ...notTracked },
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
    const conversions = tracked ? impact.after_click : impact.without_click
    steps.push(
        event && conversions
            ? {
                  key: 'converted',
                  label: event,
                  value: conversions.converted,
                  share: share(conversions.converted, conversions.sends),
                  ...conversionBase(conversions.sends, tracked ? impact.clicked : impact.delivered, tracked),
              }
            : { key: 'converted', label: 'Converted', value: null, share: null, missing: 'Pick an event' }
    )
    return steps
}

function clickedStep(impact: TransactionalEmailImpactApi): ImpactStep {
    const step = { key: 'clicked', label: 'Clicked', value: impact.clicked } as const
    return impact.clicked > impact.opened
        ? { ...step, share: share(impact.clicked, impact.delivered), shareOf: 'delivered' }
        : { ...step, share: share(impact.clicked, impact.opened) }
}

function conversionBase(followed: number, of: number, tracked: boolean): Pick<ImpactStep, 'shareOf' | 'shareDetail'> {
    const step = tracked ? 'clicked' : 'delivered'
    if (followed >= of) {
        return { shareOf: step }
    }
    return {
        shareOf: `${humanFriendlyNumber(followed)} followed`,
        shareDetail: `PostHog follows the sends that name a person, and only the most recent ones on a busy email, so this counts ${humanFriendlyNumber(followed)} of ${humanFriendlyNumber(of)} ${step} sends.`,
    }
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

export function followedSendsNote(impact: TransactionalEmailImpactApi): string | null {
    const tracked = clicksTracked(impact)
    const parts: string[] = []
    if (tracked && impact.after_click && impact.after_click.sends < impact.clicked) {
        parts.push(
            `${humanFriendlyNumber(impact.after_click.sends)} of ${humanFriendlyNumber(impact.clicked)} clicked sends`
        )
    }
    const unclicked = tracked ? impact.delivered - impact.clicked : impact.delivered
    if (impact.without_click && impact.without_click.sends < unclicked) {
        const label = tracked ? 'sends nobody clicked' : 'delivered sends'
        parts.push(`${humanFriendlyNumber(impact.without_click.sends)} of ${humanFriendlyNumber(unclicked)} ${label}`)
    }
    return parts.length > 0
        ? `Counted over ${parts.join(' and ')}: PostHog follows the sends that name a person, and only the most recent ones on a busy email.`
        : null
}
