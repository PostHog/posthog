import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Button } from 'lib/ui/quill'

import { PropertyOperator } from '~/types'

import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { IssueFilterPreviewHeader } from '../IssueFilterPreview/IssueFilterPreviewHeader'
import { issueFilterPreviewLogic } from '../IssueFilterPreview/issueFilterPreviewLogic'
import { FingerprintList } from './FingerprintList'
import { fingerprintSamplesLogic } from './fingerprintSamplesLogic'
import { manageFingerprintsLogic } from './manageFingerprintsLogic'

export function FingerprintPreview({ issueId }: { issueId: string }): JSX.Element {
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')
    const { issueFingerprints, issueFingerprintsLoading } = useValues(errorTrackingIssueSceneLogic)
    const { samples, samplesLoading } = useValues(fingerprintSamplesLogic({ issueId }))
    const { applyPropertyFilter } = useActions(issueFilterPreviewLogic)
    const { openManage } = useActions(manageFingerprintsLogic({ issueId }))

    const filterByFingerprint = (fingerprint: string): void => {
        applyPropertyFilter('$exception_fingerprint', fingerprint, PropertyOperator.Exact, true)
    }

    return (
        <div className="flex flex-col">
            <IssueFilterPreviewHeader preview="fingerprints" title="Fingerprints">
                {hasIssueSplitting && (
                    <Button
                        variant="default"
                        size="sm"
                        onClick={openManage}
                        data-attr="error-tracking-manage-fingerprints"
                    >
                        Manage
                    </Button>
                )}
            </IssueFilterPreviewHeader>
            <div className="flex h-64 min-h-0 flex-col p-1">
                <FingerprintList
                    fingerprints={issueFingerprints}
                    samples={samples}
                    loading={issueFingerprintsLoading || samplesLoading}
                    onSelect={filterByFingerprint}
                />
            </div>
        </div>
    )
}
