import { useValues } from 'kea'
import { useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonTag } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { REPLAY_FILTERS_ENTRY_POINT } from '../replayFiltersScannerLogic'
import type { ScannerHandoffFromFilters } from '../scannerHandoffFromFilters'
import { ReplayFiltersScannerButton } from './ReplayFiltersScannerButton'

/** The Replay vision entry point in the replay filters footer. */
export function ReplayFiltersScannerEntryPoint({
    handoff,
}: {
    handoff: ScannerHandoffFromFilters
}): JSX.Element | null {
    // ReplayVisionCloudOnly refuses every vision request on self-hosted. Same gate as useVisionSurfaceShown.
    const { isHobby } = useValues(preflightLogic)
    // Rendering the real button mounts visionQuotaLogic, which fetches quota and billing on mount and
    // polls while billing sync is pending. Opening the filters must not pay for an unopened popover.
    const [opened, setOpened] = useState(false)

    if (isHobby) {
        return null
    }

    return (
        <>
            {opened ? (
                <ReplayFiltersScannerButton handoff={handoff} openOnMount />
            ) : (
                <ReplayFiltersScannerPlaceholderButton handoff={handoff} onOpen={() => setOpened(true)} />
            )}
            {/* Grouped away from the buttons that act on the filters themselves: this one leaves for another product. */}
            <LemonDivider vertical className="mx-1 self-stretch" />
        </>
    )
}

/** Same button, no scanner logic and no quota request. */
function ReplayFiltersScannerPlaceholderButton({
    handoff,
    onOpen,
}: {
    handoff: ScannerHandoffFromFilters
    onOpen: () => void
}): JSX.Element {
    return (
        <PostHogCaptureOnViewed
            // Pinned: shared with the other Replay vision upsells, so one funnel compares every placement.
            name="replay_vision_upsell_shown"
            properties={{ placement: REPLAY_FILTERS_ENTRY_POINT, narrows_sessions: handoff.narrowsSessions }}
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
                // Frozen: autocapture and the filters story find the entry point by it.
                data-attr="replay-save-filters-as-scanner"
                onClick={onOpen}
            >
                {handoff.narrowsSessions ? 'Have AI watch recordings like these' : 'Have AI watch new recordings'}
            </LemonButton>
        </PostHogCaptureOnViewed>
    )
}
