import { IconPlayFilled } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

interface ExampleClip {
    scannerName: string
    scannerType: string
    headline: string
    reason: string
}

/**
 * Invented, not sampled. A reader with no scanners has no observations to preview, so these stand in
 * for the shape of a card rather than for anything their project has recorded.
 */
const EXAMPLE_CLIPS: ExampleClip[] = [
    {
        scannerName: 'Checkout friction',
        scannerType: 'Monitor',
        headline: 'Repeated clicks on a payment button that stayed disabled',
        reason: 'The scanner answered yes for this session.',
    },
    {
        scannerName: 'Onboarding drop-off',
        scannerType: 'Summarizer',
        headline: 'Went back and forth between plans, then closed the tab',
        reason: 'The scanner raised a UX friction signal from this session.',
    },
    {
        scannerName: 'Search quality',
        scannerType: 'Scorer',
        headline: 'Three searches in a row, none of them opened',
        reason: "Scored far from this scanner's recent average.",
    },
]

export interface ExampleObservationsProps {
    /** Stacks the thumbnail above the text, for a side column too narrow for the two side by side. */
    compact?: boolean
}

/** Example observation cards, so a reader without observations of their own sees what a scanner produces. */
export function ExampleObservations({ compact = false }: ExampleObservationsProps): JSX.Element {
    return (
        <div className="relative flex flex-col gap-2">
            <p className="text-xs text-secondary m-0">Examples, not your data</p>
            {EXAMPLE_CLIPS.map((clip) => (
                <div
                    key={clip.scannerName}
                    className={cn(
                        'flex border rounded bg-bg-light',
                        compact ? 'flex-col gap-2 p-3' : 'gap-4 items-start p-4'
                    )}
                >
                    <div
                        className={cn(
                            'flex-none rounded bg-surface-secondary flex items-center justify-center text-secondary',
                            compact ? 'w-full h-16' : 'w-40 h-24'
                        )}
                    >
                        <IconPlayFilled className="text-xl" />
                    </div>
                    <div className="min-w-0 flex flex-col gap-1">
                        <div className="flex flex-wrap gap-1">
                            <LemonTag type="highlight">Example</LemonTag>
                            <LemonTag type="muted">{clip.scannerName}</LemonTag>
                            <LemonTag type="muted">{clip.scannerType}</LemonTag>
                        </div>
                        <h4 className="text-sm font-semibold m-0">{clip.headline}</h4>
                        <p className="text-xs text-secondary m-0">{clip.reason}</p>
                    </div>
                </div>
            ))}
            {/* The examples stand in for a feed the reader does not have, so the column fades into
                the page instead of ending on a hard edge, which would read as a real feed cut
                short. The stop is the scene background token, so the fade lands in both themes. */}
            <div
                aria-hidden
                className="absolute inset-0 pointer-events-none bg-gradient-to-b from-transparent from-30% to-[var(--color-bg-primary)]"
            />
        </div>
    )
}
