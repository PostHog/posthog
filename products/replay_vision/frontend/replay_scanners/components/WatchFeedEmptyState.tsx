import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { visionScannersListLogic } from '../../logics/visionScannersListLogic'
import type { WatchFeedEmptyReason } from '../watchFeedEmptyState'
import { watchFeedLogic } from '../watchFeedLogic'
import { WatchFeedIntro } from './WatchFeedIntro'

function DashedNote({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 text-sm text-secondary border border-dashed rounded p-6 text-center">
            {children}
        </div>
    )
}

/**
 * The one screen the What to watch tab shows when it has no clips. Each reason gets the next step
 * that would actually fill the feed, so a reader is never told to wait on scanners that cannot run.
 */
export function WatchFeedEmptyState({ reason }: { reason: WatchFeedEmptyReason }): JSX.Element {
    const { clearFeedFilters } = useActions(watchFeedLogic)
    const { scanners } = useValues(visionScannersListLogic)
    const { push } = useActions(router)

    if (reason === 'no-scanners') {
        return <WatchFeedIntro />
    }

    if (reason === 'all-disabled') {
        return (
            <LemonBanner
                type="warning"
                action={{
                    children: 'See all scanners',
                    onClick: () => push(urls.replayVision(), { tab: 'scanners' }),
                    'data-attr': 'vision-watch-feed-see-scanners',
                }}
            >
                <p className="font-semibold m-0">None of your scanners are running</p>
                <p className="m-0">
                    {/* Only worth counting once there are several. The list loads on its own, so a count
                        taken before it answers would read as "All 0 of your scanners". */}
                    {scanners.length > 1
                        ? `All ${scanners.length} of your scanners are off, so nothing new can reach this feed.`
                        : 'Every scanner on this project is off, so nothing new can reach this feed.'}{' '}
                    Turn one on and its clips appear after the next matching recording.
                </p>
            </LemonBanner>
        )
    }

    if (reason === 'quota-exhausted') {
        return (
            <LemonBanner
                type="warning"
                action={{
                    children: 'See usage',
                    onClick: () => push(urls.replayVision(), { tab: 'usage' }),
                    'data-attr': 'vision-watch-feed-see-usage',
                }}
            >
                <p className="font-semibold m-0">Your Replay Vision credits are used up for this period</p>
                <p className="m-0">
                    Scans are skipped until the period resets, so no new clips reach this feed. Raise the limit to start
                    them again.
                </p>
            </LemonBanner>
        )
    }

    if (reason === 'all-capped') {
        return (
            <LemonBanner
                type="warning"
                action={{
                    children: 'See usage',
                    onClick: () => push(urls.replayVision(), { tab: 'usage' }),
                    'data-attr': 'vision-watch-feed-see-usage',
                }}
            >
                <p className="font-semibold m-0">Every running scanner has reached its own credit limit</p>
                <p className="m-0">
                    They stop scanning until the period resets. Raise a scanner's limit to start it again. The sessions
                    they skipped are not scanned later.
                </p>
            </LemonBanner>
        )
    }

    if (reason === 'filtered') {
        return (
            <DashedNote>
                <span>No clips match these filters in this window.</span>
                <LemonButton type="secondary" size="small" onClick={() => clearFeedFilters()}>
                    Clear filters
                </LemonButton>
            </DashedNote>
        )
    }

    return <DashedNote>Nothing stood out in this window. Try a longer date range to see more.</DashedNote>
}
