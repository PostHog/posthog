import { IconBolt } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { RecommendationTile } from '../RecommendationTile'

export function AutocaptureTile({ onEnable }: { onEnable: () => void }): JSX.Element {
    return (
        <RecommendationTile
            tileId="autocapture-off"
            icon={<IconBolt className="text-danger" />}
            title="Exception autocapture is turned off"
            category="Configuration"
            priority="critical"
            actions={
                <LemonButton type="primary" size="small" onClick={onEnable}>
                    Turn on autocapture
                </LemonButton>
            }
        >
            <p>
                Error tracking works best with exception autocapture enabled. Without it, you're only seeing manually
                captured exceptions and missing the majority of errors happening in your application.
            </p>
            <div className="rounded-lg border border-warning bg-warning-highlight px-3 py-2 mt-1">
                <p className="text-xs mb-0">
                    <strong>What changes:</strong> The SDK will automatically capture unhandled exceptions, promise
                    rejections, and console errors — no code changes needed.
                </p>
            </div>
        </RecommendationTile>
    )
}
