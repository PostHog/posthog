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

function share(value: number, of: number): number | null {
    return of > 0 ? value / of : null
}

export function untrackedSendsNote(impact: TransactionalEmailImpactApi): string | null {
    if (impact.untracked === 0) {
        return null
    }
    const [sends, their] = impact.untracked === 1 ? ['send', 'its'] : ['sends', 'their']
    return `${humanFriendlyNumber(impact.untracked)} ${sends} in this period went out with tracking off, so ${their} opens and clicks aren't counted.`
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
    const conversions = impact.after_click
    return [
        { key: 'sent', label: 'Sent', value: impact.sent, share: null },
        { key: 'delivered', label: 'Delivered', value: impact.delivered, share: null },
        { key: 'opened', label: 'Opened', value: impact.opened, share: null },
        { key: 'clicked', label: 'Clicked', value: impact.clicked, share: null },
        {
            key: 'session',
            label: 'Started a session',
            value: null,
            share: null,
            missing: 'Needs link tagging',
            missingDetail: LINK_TAGGING_DETAIL,
        },
        event && conversions
            ? {
                  key: 'converted',
                  label: event,
                  value: conversions.converted,
                  share: share(conversions.converted, conversions.sends),
                  ...conversionBase(conversions.sends, impact.clicked),
              }
            : { key: 'converted', label: 'Converted', value: null, share: null, missing: 'Pick an event' },
    ]
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
