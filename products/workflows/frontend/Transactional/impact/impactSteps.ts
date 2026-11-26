import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

export type ImpactStepKey = 'sent' | 'delivered' | 'opened' | 'clicked' | 'session' | 'converted'

export type ImpactFunnelState = 'loading' | 'error' | 'empty' | 'ready'

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

const TRACKING_OFF_DETAIL =
    "Every send in this period went out with tracking off, so PostHog couldn't record opens or clicks."

const CLICKS_OFF_DETAIL =
    "Every send in this period went out with click tracking off, so PostHog couldn't record clicks."

function share(value: number, of: number): number | null {
    return of > 0 ? value / of : null
}

function sendsNote(count: number, off: string, uncounted: string): string | null {
    if (count === 0) {
        return null
    }
    const [sends, their] = count === 1 ? ['send', 'its'] : ['sends', 'their']
    return `${humanFriendlyNumber(count)} ${sends} in this period went out with ${off} off, so ${their} ${uncounted} aren't counted.`
}

export function untrackedSendsNote(impact: TransactionalEmailImpactApi): string | null {
    const notes = [
        sendsNote(impact.untracked, 'tracking', 'opens and clicks'),
        sendsNote(clicksUntracked(impact), 'click tracking', 'clicks'),
    ].filter((note): note is string => note !== null)
    return notes.length > 0 ? notes.join(' ') : null
}

export function impactFunnelState(
    impact: TransactionalEmailImpactApi | null,
    loading: boolean,
    error: string | null
): ImpactFunnelState {
    if (loading) {
        return 'loading'
    }
    if (error) {
        return 'error'
    }
    if (!impact) {
        return 'loading'
    }
    const recorded = impact.sent + impact.delivered + impact.opened + impact.clicked
    return recorded === 0 ? 'empty' : 'ready'
}

const MIN_VISIBLE_BAR_PERCENT = 2

export function stepBarPercents(steps: ImpactStep[]): (number | null)[] {
    const tallest = Math.max(0, ...steps.map((step) => step.value ?? 0))
    return steps.map((step) => {
        if (step.value === null) {
            return null
        }
        return step.value > 0 ? Math.max(MIN_VISIBLE_BAR_PERCENT, (step.value / tallest) * 100) : 0
    })
}

export function impactSteps(impact: TransactionalEmailImpactApi, event: string | null): ImpactStep[] {
    return [
        { key: 'sent', label: 'Sent', value: impact.sent, share: null },
        { key: 'delivered', label: 'Delivered', value: impact.delivered, share: null },
        trackedStep('opened', 'Opened', impact.opened, everySendUntracked(impact), TRACKING_OFF_DETAIL),
        trackedStep('clicked', 'Clicked', impact.clicked, everySendClicksOff(impact), clicksOffDetail(impact)),
        {
            key: 'session',
            label: 'Started a session',
            value: null,
            share: null,
            missing: 'Needs link tagging',
            missingDetail: LINK_TAGGING_DETAIL,
        },
        conversionStep(impact, event),
    ]
}

function everySendUntracked(impact: TransactionalEmailImpactApi): boolean {
    const nothingRecorded = impact.opened === 0 && impact.clicked === 0
    return nothingRecorded && impact.untracked > 0 && impact.untracked >= impact.sent
}

function clicksUntracked(impact: TransactionalEmailImpactApi): number {
    return impact.clicks_untracked ?? 0
}

export function everySendClicksOff(impact: TransactionalEmailImpactApi): boolean {
    const clicksOff = impact.untracked + clicksUntracked(impact)
    return impact.clicked === 0 && clicksOff > 0 && clicksOff >= impact.sent
}

function clicksOffDetail(impact: TransactionalEmailImpactApi): string {
    return everySendUntracked(impact) ? TRACKING_OFF_DETAIL : CLICKS_OFF_DETAIL
}

function trackedStep(
    key: ImpactStepKey,
    label: string,
    value: number,
    trackingOff: boolean,
    missingDetail: string
): ImpactStep {
    if (value === 0 && trackingOff) {
        return { key, label, value: null, share: null, missing: 'Tracking off', missingDetail }
    }
    return { key, label, value, share: null }
}

function conversionStep(impact: TransactionalEmailImpactApi, event: string | null): ImpactStep {
    const conversions = impact.after_click
    if (!event || !conversions) {
        return { key: 'converted', label: 'Converted', value: null, share: null, missing: 'Pick an event' }
    }
    if (conversions.sends === 0) {
        return { key: 'converted', label: event, value: null, share: null, ...noClickToFollow(impact) }
    }
    return {
        key: 'converted',
        label: event,
        value: conversions.converted,
        share: share(conversions.converted, conversions.sends),
        ...conversionBase(conversions.sends, impact.clicked),
    }
}

function noClickToFollow(impact: TransactionalEmailImpactApi): Pick<ImpactStep, 'missing' | 'missingDetail'> {
    if (impact.clicked > 0) {
        const sends =
            impact.clicked === 1
                ? 'the clicked send'
                : `any of the ${humanFriendlyNumber(impact.clicked)} clicked sends`
        return {
            missing: 'None followed',
            missingDetail: `PostHog couldn't tie ${sends} in this period to a person.`,
        }
    }
    if (everySendClicksOff(impact)) {
        return {
            missing: 'Tracking off',
            missingDetail: `This counts conversions after a click. ${clicksOffDetail(impact)}`,
        }
    }
    return {
        missing: 'No clicks',
        missingDetail: 'This counts conversions after a click, and no clicks were recorded in this period.',
    }
}

export function noClickReason(impact: TransactionalEmailImpactApi): string {
    if (everySendUntracked(impact)) {
        return 'No clicks were recorded, because every send in this period went out with tracking off.'
    }
    return everySendClicksOff(impact)
        ? 'No clicks were recorded, because every send in this period went out with click tracking off.'
        : 'No clicks were recorded in this period.'
}

function conversionBase(followed: number, of: number): Pick<ImpactStep, 'shareOf' | 'shareDetail'> {
    if (followed >= of) {
        return { shareOf: 'clicked' }
    }
    return {
        shareOf: `${humanFriendlyNumber(followed)} followed`,
        shareDetail: `PostHog follows the sends that name a person, and only the most recent ones on a busy email, so this counts ${humanFriendlyNumber(followed)} of ${humanFriendlyNumber(of)} clicked sends.`,
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
    const parts: string[] = []
    if (impact.after_click && impact.after_click.sends < impact.clicked) {
        parts.push(
            `${humanFriendlyNumber(impact.after_click.sends)} of ${humanFriendlyNumber(impact.clicked)} clicked sends`
        )
    }
    if (impact.without_click && impact.without_click.sends < impact.not_clicked) {
        parts.push(
            `${humanFriendlyNumber(impact.without_click.sends)} of ${humanFriendlyNumber(impact.not_clicked)} delivered sends with no recorded click`
        )
    }
    return parts.length > 0
        ? `Counted over ${parts.join(' and ')}: PostHog follows the sends that name a person, and only the most recent ones on a busy email.`
        : null
}
