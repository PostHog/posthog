import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { emailImpactLogic } from './emailImpactLogic'
import { ImpactFunnel } from './ImpactFunnel'
import { ImpactLiftLine } from './ImpactLiftLine'

export function ImpactFunnelCard(): JSX.Element {
    const { impact, impactLoading, impactFailed, steps, event } = useValues(emailImpactLogic)
    const { loadImpact } = useActions(emailImpactLogic)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-4 p-4">
            <h3 className="m-0 text-base font-semibold">
                {event ? `From send to "${event}"` : 'From send to conversion'}
            </h3>
            {impactFailed && !impactLoading ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => loadImpact(), 'data-attr': 'email-impact-retry' }}
                >
                    This email's impact couldn't load. Try again, or pick a shorter period.
                </LemonBanner>
            ) : !impact || !steps ? (
                <LemonSkeleton className="h-44" />
            ) : impact.sent === 0 ? (
                <p className="text-secondary text-sm m-0">Nobody was sent this email in this period.</p>
            ) : (
                <>
                    <ImpactFunnel steps={steps} />
                    <ImpactLiftLine />
                </>
            )}
        </LemonCard>
    )
}
