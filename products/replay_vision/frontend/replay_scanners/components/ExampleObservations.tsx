import { IconPlayFilled } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { ScannerType, scannerTypeLabel } from '../types'

export interface ExampleClip {
    scannerName: string
    scannerType: ScannerType
    headline: string
    reason: string
    why: string
    watchFrom: string
}

/**
 * Invented, not sampled. A reader with no scanners has no observations to preview, so these stand in
 * for the shape of a card rather than for anything their project has recorded.
 */
export const EXAMPLE_CLIPS: ExampleClip[] = [
    {
        scannerName: 'Checkout friction',
        scannerType: 'monitor',
        headline: 'Repeated clicks on a payment button that stayed disabled',
        reason: 'The scanner answered yes for this session.',
        why: 'Something failed here and in 6 similar sessions.',
        watchFrom: '01:12',
    },
    {
        scannerName: 'Onboarding drop-off',
        scannerType: 'summarizer',
        headline: 'Went back and forth between plans, then closed the tab',
        reason: 'The scanner raised a UX friction signal from this session.',
        why: 'The user struggled in this session.',
        watchFrom: '03:40',
    },
    {
        scannerName: 'Search quality',
        scannerType: 'scorer',
        headline: 'Three searches in a row, none of them opened',
        reason: "Scored far from this scanner's recent average.",
        why: 'The user struggled here and in 2 similar sessions.',
        watchFrom: '00:48',
    },
    {
        scannerName: 'Billing errors',
        scannerType: 'monitor',
        headline: 'The invoice page showed an error after a plan change',
        reason: 'The scanner answered yes for this session.',
        why: 'A payment problem came up in this session.',
        watchFrom: '02:05',
    },
]

/** Example observation cards, so a reader without observations of their own sees what a scanner produces. */
export function ExampleObservations(): JSX.Element {
    return (
        <div className="relative flex flex-col gap-2">
            <p className="text-xs text-secondary m-0">Examples, not your data</p>
            {EXAMPLE_CLIPS.map((clip) => (
                <div key={clip.scannerName} className="flex flex-col gap-2 border rounded bg-bg-light p-3">
                    <div className="flex-none w-full h-16 rounded bg-surface-secondary flex items-center justify-center text-secondary">
                        <IconPlayFilled className="text-xl" />
                    </div>
                    <div className="min-w-0 flex flex-col gap-1">
                        <div className="flex flex-wrap gap-1">
                            <LemonTag type="highlight">Example</LemonTag>
                            <LemonTag type="muted">{clip.scannerName}</LemonTag>
                            <LemonTag type="muted">{scannerTypeLabel(clip.scannerType)}</LemonTag>
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
