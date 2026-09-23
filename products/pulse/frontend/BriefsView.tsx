import { useActions, useValues } from 'kea'

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

    // The scene-level empty state covers a project with no briefs at all. This branch is the
    // per-focus case: briefs exist, but none for the selected focus yet.
    if (visibleBriefs.length === 0) {
        return (
            <div className="flex flex-col items-center gap-3 border rounded p-8 text-center">
                <span className="text-secondary">No briefs for this focus yet.</span>
                <RunBriefButton />
            </div>
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
