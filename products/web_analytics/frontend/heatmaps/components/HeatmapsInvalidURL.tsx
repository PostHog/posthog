import { LemonBanner } from '@posthog/lemon-ui'

export function HeatmapsInvalidURL(): JSX.Element {
    return (
        <div className="flex-1 py-4 gap-y-4 mb-2">
            <LemonBanner type="error">Not a valid URL. Can't load a heatmap for that 😰</LemonBanner>
        </div>
    )
}
