import { IconPlayFilled } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { VisionDocsLink } from '../../components/DocsLink'
import { CreateScannerButton } from './CreateScannerButton'

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

/**
 * What the What to watch tab shows a reader who has no scanners: what the feed is for, an example of
 * the card it fills with, and the way to start one.
 */
export function WatchFeedIntro(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col items-center gap-2 text-center">
                <h3 className="text-xl font-semibold m-0">See your most notable observations here</h3>
                <p className="text-secondary m-0 max-w-lg">
                    Scanners watch each new session recording and cite the moment they found. We surface the most
                    notable ones here.
                </p>
                <div className="flex flex-wrap items-center justify-center gap-2 mt-1">
                    <CreateScannerButton
                        acceptedLabel="Create your first scanner"
                        dataAttr="vision-watch-feed-create-scanner"
                        size="medium"
                    />
                    <VisionDocsLink page="creating-scanners" dataAttr="vision-watch-feed-docs-link">
                        Learn how scanners work
                    </VisionDocsLink>
                </div>
            </div>

            <div className="relative flex flex-col gap-2">
                <p className="text-xs text-secondary m-0">Examples, not your data</p>
                {EXAMPLE_CLIPS.map((clip) => (
                    <div key={clip.scannerName} className="flex gap-4 items-start border rounded bg-bg-light p-4">
                        <div className="flex-none w-40 h-24 rounded bg-surface-secondary flex items-center justify-center text-secondary">
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
        </div>
    )
}
