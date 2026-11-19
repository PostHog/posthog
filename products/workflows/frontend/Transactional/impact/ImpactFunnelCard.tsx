import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { emailImpactLogic } from './emailImpactLogic'
import { ImpactFunnel } from './ImpactFunnel'
import { ImpactLiftLine } from './ImpactLiftLine'
import { emptyPeriodMessage } from './impactSteps'

export function ImpactFunnelCard(): JSX.Element {
    const { event } = useValues(emailImpactLogic)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-4 p-4">
            <h3 className="m-0 text-base font-semibold">
                {event ? `From send to "${event}"` : 'From send to conversion'}
            </h3>
            <FunnelBody />
        </LemonCard>
    )
}

function FunnelBody(): JSX.Element {
    const { funnelState, impact, impactError, steps, untrackedNote } = useValues(emailImpactLogic)
    const { loadImpact, linkTaggingSettingsOpened } = useActions(emailImpactLogic)

    if (funnelState === 'error') {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadImpact(), 'data-attr': 'email-impact-retry' }}
            >
                {impactError}
            </LemonBanner>
        )
    }
    if (funnelState === 'empty' && impact) {
        return (
            <>
                <p className="text-secondary text-sm m-0">{emptyPeriodMessage(impact)}</p>
                {untrackedNote && <p className="text-secondary text-sm m-0">{untrackedNote}</p>}
            </>
        )
    }
    if (funnelState === 'loading' || !steps) {
        return <LemonSkeleton className="h-44" />
    }
    return (
        <>
            <ImpactFunnel steps={steps} onSettingsLinkOpened={linkTaggingSettingsOpened} />
            {untrackedNote && <p className="text-secondary text-sm m-0">{untrackedNote}</p>}
            <ImpactLiftLine />
        </>
    )
}
