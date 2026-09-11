import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconSparkles } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Button } from 'lib/ui/quill'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { markScannerHandoffIntent } from 'products/replay_vision/frontend/replay_scanners/scannerHandoffIntent'

import { errorTrackingIssueSceneLogic } from '../../../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { getIssueReplayDateRange, issueVisionScannerHandoff } from '../../../../utils'

/** Cross-sell from an issue's Recording tab into Replay vision: arms a one-shot hand-off with a
 * scanner prefilled for this issue, then opens the wizard on its review-and-create summary. The
 * tab only renders when the exception carries a session ID, so there is at least one recording
 * for the scanner's priming pass to watch. */
export function ScanWithVisionButton(): JSX.Element | null {
    const { issue, lastSeen, selectedEvent, initialEventTimestamp } = useValues(errorTrackingIssueSceneLogic)
    const crossSellEnabled = useFeatureFlag('VISION_ENTRYPOINT_ERROR_TRACKING')

    const issueName = issue?.name
    if (!crossSellEnabled || !issue || !issueName) {
        return null
    }

    return (
        <Button
            variant="default"
            size="sm"
            data-attr="error-tracking-scan-with-vision"
            onClick={() => {
                markScannerHandoffIntent(
                    issueVisionScannerHandoff(
                        issue.id,
                        issueName,
                        getIssueReplayDateRange(
                            issue.first_seen,
                            lastSeen,
                            selectedEvent?.timestamp ?? initialEventTimestamp
                        )
                    )
                )
                void addProductIntentForCrossSell({
                    from: ProductKey.ERROR_TRACKING,
                    to: ProductKey.REPLAY_VISION,
                    intent_context: ProductIntentContext.ERROR_TRACKING_SCAN_WITH_VISION,
                })
                router.actions.push(urls.replayVisionScannerOverview('new'))
            }}
        >
            <IconSparkles className="text-ai" />
            Scan recordings with Replay vision
        </Button>
    )
}
