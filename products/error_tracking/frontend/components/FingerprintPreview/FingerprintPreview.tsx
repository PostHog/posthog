import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Button, ToggleGroup, ToggleGroupItem, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import { PropertyOperator } from '~/types'

import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { IssueFilterPreviewHeader } from '../IssueFilterPreview/IssueFilterPreviewHeader'
import { issueFilterPreviewLogic } from '../IssueFilterPreview/issueFilterPreviewLogic'
import { FingerprintList } from './FingerprintList'
import { FingerprintMap } from './FingerprintMap'
import { fingerprintProjectionLogic } from './fingerprintProjectionLogic'
import { fingerprintSamplesLogic } from './fingerprintSamplesLogic'
import { manageFingerprintsLogic } from './manageFingerprintsLogic'
import { similarFingerprintsLogic } from './similarFingerprintsLogic'
import { SimilarFingerprintsModal } from './SimilarFingerprintsModal'

export function FingerprintPreview({ issueId }: { issueId: string }): JSX.Element {
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')
    const { fingerprintDomains, fingerprintSeries, projection, projectionError, projectionLoading } = useValues(
        fingerprintProjectionLogic({ issueId })
    )
    const { loadProjection } = useActions(fingerprintProjectionLogic({ issueId }))
    const { issueFingerprints, issueFingerprintsLoading } = useValues(errorTrackingIssueSceneLogic)
    const { samples, samplesLoading } = useValues(fingerprintSamplesLogic({ issueId }))
    const { fingerprintsViewMode } = useValues(issueFilterPreviewLogic)
    const { applyPropertyFilter, setFingerprintsViewMode } = useActions(issueFilterPreviewLogic)
    const { openSimilar } = useActions(similarFingerprintsLogic({ issueId }))
    const { openManage } = useActions(manageFingerprintsLogic({ issueId }))

    const filterByFingerprint = (fingerprint: string): void => {
        applyPropertyFilter('$exception_fingerprint', fingerprint, PropertyOperator.Exact, true)
    }

    const mapUnavailable = !projectionLoading && projectionError === null && projection.results.length === 0
    // The view mode persists across issues, so an issue without embeddings has to fall back on its own.
    const viewMode = mapUnavailable ? 'list' : fingerprintsViewMode

    const mapToggleItem = (
        <ToggleGroupItem value="map" disabled={mapUnavailable} data-attr="error-tracking-fingerprints-view-map">
            Map
        </ToggleGroupItem>
    )

    return (
        <div className="flex flex-col">
            <IssueFilterPreviewHeader preview="fingerprints" title="Fingerprints">
                <div className="flex w-full items-center justify-between gap-3">
                    <ToggleGroup
                        size="sm"
                        aria-label="Fingerprints view"
                        value={[viewMode]}
                        onValueChange={(value) => {
                            const next = value[0]
                            if (next === 'list' || next === 'map') {
                                setFingerprintsViewMode(next)
                            }
                        }}
                    >
                        <ToggleGroupItem value="list" data-attr="error-tracking-fingerprints-view-list">
                            List
                        </ToggleGroupItem>
                        {mapUnavailable ? (
                            <Tooltip>
                                <TooltipTrigger render={<span className="inline-flex" />}>
                                    {mapToggleItem}
                                </TooltipTrigger>
                                <TooltipContent>No fingerprint embeddings for this issue yet.</TooltipContent>
                            </Tooltip>
                        ) : (
                            mapToggleItem
                        )}
                    </ToggleGroup>
                    {hasIssueSplitting && (
                        <Button
                            variant="default"
                            size="sm"
                            onClick={openManage}
                            data-attr="error-tracking-manage-fingerprints"
                        >
                            Manage fingerprints
                        </Button>
                    )}
                </div>
            </IssueFilterPreviewHeader>
            <div className="flex h-64 min-h-0 flex-col px-3 pb-3 pt-2">
                {viewMode === 'map' ? (
                    <FingerprintMap
                        domains={fingerprintDomains}
                        series={fingerprintSeries}
                        hasMore={projection.hasMore}
                        loading={projectionLoading}
                        error={projectionError}
                        onRetry={loadProjection}
                        onSelect={filterByFingerprint}
                    />
                ) : (
                    <FingerprintList
                        fingerprints={issueFingerprints}
                        samples={samples}
                        loading={issueFingerprintsLoading || samplesLoading}
                        onSelect={filterByFingerprint}
                        onFindSimilar={openSimilar}
                    />
                )}
            </div>
            <SimilarFingerprintsModal issueId={issueId} samples={samples} />
        </div>
    )
}
