import { useActions } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { replayFiltersScannerLogic } from '../replayFiltersScannerLogic'
import type { ScannerHandoffFromFilters } from '../scannerHandoffFromFilters'
import { ReplayFiltersScannerButton } from './ReplayFiltersScannerButton'

/** The Replay vision entry point in the replay filters footer. The team flag shows the popover,
 * everyone else gets the button that opens the wizard. */
export function ReplayFiltersScannerEntryPoint({ handoff }: { handoff: ScannerHandoffFromFilters }): JSX.Element {
    const teamEntryPoint = useFeatureFlag('VISION_ENTRYPOINT_REPLAY_FILTERS')

    return (
        <>
            {teamEntryPoint ? (
                <ReplayFiltersScannerButton handoff={handoff} />
            ) : (
                <ReplayFiltersCreateScannerButton handoff={handoff} />
            )}
            {/* Grouped away from the buttons that act on the filters themselves: this one leaves for another product. */}
            <LemonDivider vertical className="mx-1 self-stretch" />
        </>
    )
}

/** Its own component so the scanner logic, and the quota requests its connected
 * logic makes on mount, only start when a button renders. */
function ReplayFiltersCreateScannerButton({ handoff }: { handoff: ScannerHandoffFromFilters }): JSX.Element {
    const { createScanner } = useActions(replayFiltersScannerLogic)

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconSparkles className="text-ai" />}
            // The same attr as the popover button, so autocapture and the filters story find either one.
            data-attr="replay-save-filters-as-scanner"
            tooltip={
                handoff.narrowsSessions
                    ? 'Create a Replay vision scanner. It watches new session recordings that match these filters for you. The date range does not carry over, so it starts from now.'
                    : 'Create a Replay vision scanner. It watches every new session recording for you. Add a filter to watch only some of them. A date range and pinned sessions do not carry over.'
            }
            onClick={() => createScanner(handoff)}
        >
            Create scanner
        </LemonButton>
    )
}
