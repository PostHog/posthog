import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { Popover } from 'lib/lemon-ui/Popover/Popover'

import { REPLAY_FILTERS_ENTRY_POINT, replayFiltersScannerLogic } from '../replayFiltersScannerLogic'
import type { ScannerHandoffFromFilters } from '../scannerHandoffFromFilters'
import { ReplayFiltersScannerPopover } from './ReplayFiltersScannerPopover'

export function ReplayFiltersScannerButton({ handoff }: { handoff: ScannerHandoffFromFilters }): JSX.Element {
    const { popoverOpen } = useValues(replayFiltersScannerLogic)
    const { setPopoverOpen } = useActions(replayFiltersScannerLogic)
    const buttonRef = useRef<HTMLButtonElement>(null)

    return (
        <PostHogCaptureOnViewed
            // Pinned: shared with the other Replay vision upsells, so one funnel compares every placement.
            name="replay_vision_upsell_shown"
            properties={{ placement: REPLAY_FILTERS_ENTRY_POINT, narrows_sessions: handoff.narrowsSessions }}
        >
            <Popover
                visible={popoverOpen}
                // Otherwise a press on the button closes the popover and the button's own toggle reopens it.
                onClickOutside={(event) => {
                    if (!buttonRef.current?.contains(event.target as Node)) {
                        setPopoverOpen(false)
                    }
                }}
                overlay={<ReplayFiltersScannerPopover handoff={handoff} />}
                placement="top-end"
                fallbackPlacements={['bottom-end']}
                showArrow
            >
                <LemonButton
                    ref={buttonRef}
                    type="secondary"
                    size="small"
                    icon={<IconSparkles className="text-ai" />}
                    sideIcon={
                        <LemonTag type="completion" size="small">
                            NEW
                        </LemonTag>
                    }
                    active={popoverOpen}
                    // Frozen: autocapture and the filters story find the entry point by it.
                    data-attr="replay-save-filters-as-scanner"
                    onClick={() => setPopoverOpen(!popoverOpen)}
                >
                    {handoff.narrowsSessions ? 'Have AI watch recordings like these' : 'Have AI watch new recordings'}
                </LemonButton>
            </Popover>
        </PostHogCaptureOnViewed>
    )
}
