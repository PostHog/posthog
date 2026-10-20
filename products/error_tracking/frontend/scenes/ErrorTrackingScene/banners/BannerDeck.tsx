import { ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

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
    if (banners.length <= 1) {
        return <>{renderCurrent()}</>
    }

    const cardsBehind = Math.min(banners.length - 1, 2)

    return (
        <div className={cn('relative', cardsBehind === 2 ? 'pb-4' : 'pb-2')}>
            {cardsBehind === 2 && (
                <div
                    aria-hidden
                    className="absolute inset-x-6 bottom-0 h-8 rounded border border-primary bg-surface-primary"
                />
            )}
            <div
                aria-hidden
                className={cn(
                    'absolute inset-x-3 h-8 rounded border border-primary bg-surface-primary',
                    cardsBehind === 2 ? 'bottom-2' : 'bottom-0'
                )}
            />
            <div className="relative">
                {renderCurrent(
                    <BannerStackControls
                        index={banners.indexOf(current)}
                        total={banners.length}
                        onPrevious={onPrevious}
                        onNext={onNext}
                    />
                )}
            </div>
        </div>
    )
}
