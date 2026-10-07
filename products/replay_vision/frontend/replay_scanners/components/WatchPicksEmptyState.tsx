import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import * as townCrierPng from '@posthog/brand/hoggies/png/town-crier'
import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { visionScannersListLogic } from '../../logics/visionScannersListLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { resolveWatchFeedEmptyReason } from '../watchFeedEmptyState'

const HedgehogTownCrier = pngHoggie(townCrierPng)
const DEFAULT_GOAL =
    'Watch sessions and give me an overview of what people are doing in the product, so I know which sessions to look at, why, and where the interesting moment is.'

export function WatchPicksEmptyState({ size }: { size: 'small' | 'large' }): JSX.Element {
    const { scanners, scannersLoading } = useValues(visionScannersListLogic)
    const { quota, quotaLoading } = useValues(visionQuotaLogic)
    const { push } = useActions(router)
    const large = size === 'large'

    if (scannersLoading || quotaLoading) {
        return <LemonSkeleton className={cn('w-full rounded', large ? 'h-64' : 'h-40')} />
    }

    const reason = resolveWatchFeedEmptyReason({ scanners, quota, hasFeedFilters: false })

    let title: string
    let body: string
    let action: JSX.Element
    switch (reason) {
        case 'no-scanners':
            title = 'Set up your first scanner'
            body =
                'Tell a scanner what to look for and it watches recordings for you. Start with the default goal or write your own.'
            action = (
                <div className="flex flex-wrap items-center justify-center gap-2">
                    <LemonButton
                        type="primary"
                        size={large ? 'medium' : 'small'}
                        disabledReason={getReplayVisionEditDisabledReason()}
                        onClick={() => push(urls.replayVisionTemplates(), { goal: DEFAULT_GOAL, draft: true })}
                        data-attr="vision-watch-picks-draft-scanner"
                    >
                        Draft my scanner
                    </LemonButton>
                    <Link to={urls.replayVisionTemplates()} data-attr="vision-watch-picks-browse-templates">
                        Write my own goal
                    </Link>
                </div>
            )
            break
        case 'all-disabled':
            title = 'None of your scanners are running'
            body = 'Turn one on and its picks appear after the next matching recording.'
            action = (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => push(urls.replayVision(), { tab: 'scanners' })}
                    data-attr="vision-watch-picks-see-scanners"
                >
                    See scanners
                </LemonButton>
            )
            break
        case 'quota-exhausted':
            title = 'Your Replay vision credits are used up for this period'
            body = 'Scans are skipped until the period resets. Raise the limit to start them again.'
            action = (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => push(urls.replayVision(), { tab: 'usage' })}
                    data-attr="vision-watch-picks-see-usage"
                >
                    See usage
                </LemonButton>
            )
            break
        default:
            title = 'Nothing to watch yet'
            body = 'Your scanners are running. Picks appear here as they flag new recordings.'
            action = (
                <Link to={urls.replayVision()} data-attr="vision-watch-picks-empty-link">
                    Open Replay vision
                </Link>
            )
    }

    return (
        <div
            className={cn(
                'flex flex-col items-center gap-2 text-center text-secondary',
                large ? 'rounded border bg-bg-light p-8 text-sm' : 'p-4 text-xs'
            )}
        >
            <HedgehogTownCrier className={large ? 'h-48 w-48' : 'h-24 w-24'} />
            <span className={cn('font-semibold text-default', large ? 'text-lg' : 'text-sm')}>{title}</span>
            <span className="max-w-lg">{body}</span>
            <div className="mt-1">{action}</div>
        </div>
    )
}
