import { ReactNode } from 'react'

import type { ErrorTrackingBannerKey } from './bannerQueue'
import { BannerStackControls } from './BannerStackControls'

export function BannerDeck({
    banners,
    current,
    onPrevious,
    onNext,
    renderCurrent,
}: {
    banners: ErrorTrackingBannerKey[]
    current: ErrorTrackingBannerKey
    onPrevious: () => void
    onNext: () => void
    /** Renders the current banner, with the stack controls to place inside it. */
    renderCurrent: (navigation?: ReactNode) => ReactNode
}): JSX.Element {
    const cardsBehind = Math.min(banners.length - 1, 2)

    // The current banner keeps the same place in the tree for any deck size. A different wrapper
    // for a single banner would remount it when the queue grows or shrinks, which closes an open
    // setup modal and loses what the user typed in it.
    // Each card behind renders only the strip that shows below the current banner, in normal flow.
    // Then no element overlaps the banner, and the deck needs no positioning or padding offsets.
    return (
        <div>
            {renderCurrent(
                cardsBehind >= 1 ? (
                    <BannerStackControls
                        index={banners.indexOf(current)}
                        total={banners.length}
                        onPrevious={onPrevious}
                        onNext={onNext}
                    />
                ) : undefined
            )}
            {cardsBehind >= 1 && (
                <div aria-hidden className="mx-3 h-2 rounded-b border border-t-0 border-primary bg-surface-primary" />
            )}
            {cardsBehind === 2 && (
                <div aria-hidden className="mx-6 h-2 rounded-b border border-t-0 border-primary bg-surface-primary" />
            )}
        </div>
    )
}
