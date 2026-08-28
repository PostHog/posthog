import { useActions, useValues } from 'kea'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { BriefDetail } from './BriefDetail'
import { BriefHistoryList } from './BriefHistoryList'
import { pulseLogic } from './pulseLogic'
import { RunBriefButton } from './RunBriefButton'

export function BriefsView(): JSX.Element {
    const { visibleBriefs, briefsLoading, briefsLoadFailed } = useValues(pulseLogic)
    const { loadBriefs } = useActions(pulseLogic)

    if (briefsLoading && visibleBriefs.length === 0) {
        return (
            <div className="flex justify-center py-16">
                <Spinner className="text-2xl" />
            </div>
        )
    }

    // A failed load must not masquerade as the "no briefs yet" onboarding — offer a retry instead.
    if (briefsLoadFailed && visibleBriefs.length === 0) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadBriefs }}>
                Couldn't load your briefs. Check your connection and try again.
            </LemonBanner>
        )
    }

    if (visibleBriefs.length === 0) {
        return (
            <ProductIntroduction
                productName="Pulse"
                thingName="brief"
                titleOverride="No briefs yet"
                description="Run your first brief to see what happened in your product, why it happened, and what to build next."
                isEmpty
                actionElementOverride={<RunBriefButton />}
            />
        )
    }

    return (
        <div className="flex gap-4 items-start">
            <BriefHistoryList briefs={visibleBriefs} />
            <div className="flex-1 min-w-0">
                <BriefDetail />
            </div>
        </div>
    )
}
