import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { replayFiltersScannerLogic } from '../replayFiltersScannerLogic'
import type { ScannerHandoffFromFilters } from '../scannerHandoffFromFilters'
import { ReplayFiltersScannerButton } from './ReplayFiltersScannerButton'

/** The Replay vision entry point in the replay filters footer. The team flag always shows the popover.
 * Everyone else is in the entry point experiment: control gets the button that opens the wizard, test
 * gets the popover. */
export function ReplayFiltersScannerEntryPoint({
    handoff,
}: {
    handoff: ScannerHandoffFromFilters
}): JSX.Element | null {
    const teamEntryPoint = useFeatureFlag('VISION_ENTRYPOINT_REPLAY_FILTERS')
    const { featureFlags } = useValues(featureFlagLogic)

    // Reading the experiment flag records the exposure, so it is read only here, where the entry point
    // renders, and never for the team, who would otherwise count as exposed to an arm they do not see.
    const arm = teamEntryPoint ? 'test' : featureFlags[FEATURE_FLAGS.VISION_ENTRYPOINT_REPLAY_FILTERS_POPOVER]
    if (arm !== 'test' && arm !== 'control') {
        return null
    }

    return (
        <>
            {arm === 'test' ? (
                <ReplayFiltersScannerButton handoff={handoff} />
            ) : (
                <ReplayFiltersCreateScannerButton handoff={handoff} />
            )}
            {/* Grouped away from the buttons that act on the filters themselves: this one leaves for another product. */}
            <LemonDivider vertical className="mx-1 self-stretch" />
        </>
    )
}

/** The control arm. Its own component so the scanner logic, and the quota requests its connected
 * logic makes on mount, only start when a button renders. */
function ReplayFiltersCreateScannerButton({ handoff }: { handoff: ScannerHandoffFromFilters }): JSX.Element {
    const { createScanner } = useActions(replayFiltersScannerLogic)

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconSparkles className="text-ai" />}
            // The same attr as the popover button, so autocapture compares the two arms.
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
