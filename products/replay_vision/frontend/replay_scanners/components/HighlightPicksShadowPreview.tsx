import { IconPlayFilled } from '@posthog/icons'

import { EXAMPLE_CLIPS } from './ExampleObservations'
import { HighlightPickRankBadge } from './HighlightPickRankBadge'

export function HighlightPicksShadowPreview(): JSX.Element {
    return (
        <div className="relative flex flex-col gap-0.5 p-1" data-attr="vision-highlight-picks-shadow-preview">
            <span className="px-2 py-1 text-xs text-secondary">Examples, not your data</span>
            {EXAMPLE_CLIPS.map((clip, index) => (
                <div key={clip.scannerName} className="flex w-full min-w-0 items-center gap-3 px-2 py-1 opacity-60">
                    <span className="relative flex h-16 w-28 shrink-0 items-center justify-center rounded bg-surface-secondary text-secondary">
                        <IconPlayFilled className="text-xl" />
                        <HighlightPickRankBadge rank={index + 1} size="small" />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className="truncate text-sm font-semibold">{clip.headline}</span>
                        <span className="truncate text-xs text-secondary">
                            {clip.scannerName} · {clip.scannerType}
                        </span>
                        <span className="truncate text-xs text-secondary">{clip.reason}</span>
                    </span>
                </div>
            ))}
            <div
                aria-hidden
                className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent from-40% to-[var(--color-bg-light)]"
            />
        </div>
    )
}
