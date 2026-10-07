import * as townCrierPng from '@posthog/brand/hoggies/png/town-crier'
import { Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

const HedgehogTownCrier = pngHoggie(townCrierPng)

export function WatchPicksEmptyState({ size }: { size: 'small' | 'large' }): JSX.Element {
    return (
        <div
            className={cn(
                'flex flex-col items-center gap-2 text-center text-sm text-secondary',
                size === 'large' ? 'rounded border bg-bg-light p-8' : 'p-4'
            )}
        >
            <HedgehogTownCrier className={size === 'large' ? 'h-48 w-48' : 'h-28 w-28'} />
            <span>Nothing to watch yet. Scanners pick out recordings worth your time as they run.</span>
            <Link to={urls.replayVision()} data-attr="vision-watch-picks-empty-link">
                Open Replay vision
            </Link>
        </div>
    )
}
