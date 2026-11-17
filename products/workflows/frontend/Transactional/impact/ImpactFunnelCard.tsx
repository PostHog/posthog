import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { emailImpactLogic } from './emailImpactLogic'
import { ImpactFunnel } from './ImpactFunnel'
import { ImpactLiftLine } from './ImpactLiftLine'

export function ImpactFunnelCard(): JSX.Element {
    const { impact, impactLoading, impactError, steps, event } = useValues(emailImpactLogic)
    const { loadImpact } = useActions(emailImpactLogic)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-4 p-4">
            <h3 className="m-0 text-base font-semibold">
                {event ? `From send to "${event}"` : 'From send to conversion'}
            </h3>
            {impactError && !impactLoading ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => loadImpact(), 'data-attr': 'email-impact-retry' }}
                >
                    {impactError}
                </LemonBanner>
            ) : impactLoading || !impact || !steps ? (
                // A reload hides the old counts, which would otherwise show under the newly picked event.
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
