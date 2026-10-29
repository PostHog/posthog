import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover/Popover'

import { replayFiltersScannerLogic } from '../replayFiltersScannerLogic'
import type { ScannerHandoffFromFilters } from '../scannerHandoffFromFilters'
import { ReplayFiltersScannerPopover } from './ReplayFiltersScannerPopover'

/** The replay filters entry point to Replay vision. Says what a scanner does, since most people
 * reaching it have not heard of one, and opens a popover that drafts one from these filters. */
export function ReplayFiltersScannerButton({ handoff }: { handoff: ScannerHandoffFromFilters }): JSX.Element {
    const { popoverOpen } = useValues(replayFiltersScannerLogic)
    const { setPopoverOpen } = useActions(replayFiltersScannerLogic)

    return (
        <Popover
            visible={popoverOpen}
            onClickOutside={() => setPopoverOpen(false)}
            overlay={<ReplayFiltersScannerPopover handoff={handoff} />}
            placement="top-end"
            fallbackPlacements={['bottom-end']}
            showArrow
        >
            <LemonButton
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
    )
}
