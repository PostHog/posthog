import { IconSparkles } from '@posthog/icons'

import { Button } from 'lib/ui/quill'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { QuickScannerPopover } from 'products/replay_vision/frontend/replay_scanners/components/QuickScannerPopover'
import type { QuickScannerLogicProps } from 'products/replay_vision/frontend/replay_scanners/quickScannerLogic'

import { issueVisionScannerPrefill } from '../../utils'

export type IssueVisionScannerPlacement = 'header' | 'recording_tab'

export function issueVisionScannerLogicProps(
    issueId: string,
    issueName: string,
    placement: IssueVisionScannerPlacement
): QuickScannerLogicProps {
    return {
        key: `error_tracking:${issueId}:${placement}`,
        // Pinned: the `placement` on the replay_vision_upsell_* events and the scanner's `entry_point`.
        entryPoint: `error_tracking_${placement}`,
        prefill: issueVisionScannerPrefill(issueId, issueName),
        productIntent: {
            from: ProductKey.ERROR_TRACKING,
            intent_context: ProductIntentContext.ERROR_TRACKING_SCAN_WITH_VISION,
        },
    }
}

export function IssueVisionScannerPopover({
    issueId,
    issueName,
    placement,
    children,
}: {
    issueId: string
    issueName: string
    placement: IssueVisionScannerPlacement
    children: (trigger: { open: boolean; toggle: () => void }) => JSX.Element
}): JSX.Element {
    return (
        <QuickScannerPopover
            logicProps={issueVisionScannerLogicProps(issueId, issueName, placement)}
            title="Have AI watch every new session with this error"
            recordingsLabel="Sessions that hit this error"
            output={
                <ul className="list-disc pl-4 m-0">
                    <li>What the user was trying to do</li>
                    <li>What they saw when the error happened</li>
                    <li>How they reacted</li>
                    <li>Whether they recovered or gave up</li>
                </ul>
            }
        >
            {children}
        </QuickScannerPopover>
    )
}

export function IssueRecordingTabVisionButton({
    issueId,
    issueName,
}: {
    issueId: string
    issueName: string
}): JSX.Element {
    return (
        <IssueVisionScannerPopover issueId={issueId} issueName={issueName} placement="recording_tab">
            {({ toggle }) => (
                <Button
                    variant="default"
                    size="sm"
                    onClick={toggle}
                    data-attr="error-tracking-recording-tab-scan-with-vision"
                >
                    <IconSparkles className="text-ai" />
                    {/* The full label does not fit beside "Open in session replay" in the narrowest pane. */}
                    <span className="hidden @xl/recording-tab:inline">
                        Have AI watch every new session with this error
                    </span>
                    <span className="@xl/recording-tab:hidden">Watch with AI</span>
                </Button>
            )}
        </IssueVisionScannerPopover>
    )
}
