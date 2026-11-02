import { IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { EXAMPLE_CLIPS } from './ExampleObservations'
import { HighlightFeedCardLayout } from './HighlightFeedCardLayout'
import { HighlightFeedScannerChip } from './HighlightFeedScannerChip'

export function HighlightFeedExampleCards(): JSX.Element {
    return (
        <div className="@container relative flex flex-col gap-2">
            <p className="m-0 text-xs text-secondary">Examples, not your data</p>
            <div className="grid grid-cols-1 gap-3 @xl:grid-cols-2">
                {EXAMPLE_CLIPS.map((card) => (
                    <HighlightFeedCardLayout
                        key={card.scannerName}
                        className="gap-2 p-3"
                        scanner={
                            <span className="flex max-w-full min-w-0 items-center gap-2 self-start text-sm text-secondary">
                                <HighlightFeedScannerChip
                                    scannerName={card.scannerName}
                                    scannerType={card.scannerType}
                                />
                            </span>
                        }
                        meta={<LemonTag type="highlight">Example</LemonTag>}
                        title={card.headline}
                        why={card.why}
                        poster={
                            <div
                                className="aspect-video flex items-center justify-center bg-surface-secondary text-secondary"
                                aria-hidden
                            >
                                <IconPlayFilled className="text-xl" />
                            </div>
                        }
                        footer={
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                icon={<IconPlayFilled />}
                                disabledReason="This is an example"
                            >
                                Watch from {card.watchFrom}
                            </LemonButton>
                        }
                    />
                ))}
            </div>
            {/* The examples stand in for a feed the reader does not have, so the grid fades into the
                page instead of ending on a hard edge, which would read as a real feed cut short. */}
            <div
                aria-hidden
                className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-b from-transparent to-[var(--color-bg-primary)]"
            />
        </div>
    )
}
