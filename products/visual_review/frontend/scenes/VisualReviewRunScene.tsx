import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonDivider, Tooltip } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { RunStatusBadge } from '../components/RunStatusBadge'
import { SnapshotDiffViewer } from '../components/SnapshotDiffViewer'
import type { SnapshotApi } from '../generated/api.schemas'
import { VisualReviewRunSceneLogicProps, visualReviewRunSceneLogic } from './visualReviewRunSceneLogic'

export const scene: SceneExport = {
    component: VisualReviewRunScene,
    logic: visualReviewRunSceneLogic,
    paramsToProps: ({ params: { runId } }): VisualReviewRunSceneLogicProps => ({
        runId: runId || '',
    }),
}

function SnapshotThumbnail({
    snapshot,
    isSelected,
    onClick,
}: {
    snapshot: SnapshotApi
    isSelected: boolean
    onClick: () => void
}): JSX.Element {
    const isApproved = snapshot.review_state === 'approved'
    const result = snapshot.result

    // Extract short name from identifier (last part after --)
    const parts = snapshot.identifier.split('--')
    const shortName = parts.length > 1 ? parts[parts.length - 1] : parts[0]

    // Status badge styling
    const getBadgeStyles = (): string => {
        if (isApproved) {
            return 'bg-success-highlight text-success-dark'
        }
        switch (result) {
            case 'changed':
                return 'bg-warning-highlight text-warning-dark'
            case 'new':
                return 'bg-primary-highlight text-primary-dark'
            case 'removed':
                return 'bg-danger-highlight text-danger'
            default:
                return 'bg-muted-alt text-muted'
        }
    }

    const getBadgeText = (): string => {
        if (isApproved) {
            return 'APPROVED'
        }
        return result?.toUpperCase() || 'UNCHANGED'
    }

    return (
        <button type="button" onClick={onClick} className="flex flex-col items-center gap-1.5 shrink-0 group">
            <div
                className={`w-24 h-16 rounded-lg overflow-hidden bg-bg-3000 transition-all border-2 ${
                    isSelected
                        ? 'border-warning-dark ring-2 ring-warning ring-offset-2'
                        : 'border-transparent group-hover:border-warning'
                }`}
            >
                {snapshot.current_artifact?.download_url ? (
                    <img
                        src={snapshot.current_artifact.download_url}
                        alt=""
                        className="w-full h-full object-cover object-top"
                    />
                ) : (
                    <div className="w-full h-full flex items-center justify-center border border-dashed border-border rounded-md">
                        <span className="text-xs text-muted">No image</span>
                    </div>
                )}
            </div>
            <Tooltip title={snapshot.identifier}>
                <span className="text-xs text-muted truncate max-w-[96px] text-center">{shortName}</span>
            </Tooltip>
            <span
                className={`text-[10px] font-semibold px-1.5 py-0.5 rounded flex items-center gap-0.5 ${getBadgeStyles()}`}
            >
                {isApproved && <IconCheck className="w-3 h-3" />}
                {getBadgeText()}
            </span>
        </button>
    )
}

export function VisualReviewRunScene(): JSX.Element {
    const {
        run,
        runLoading,
        snapshots,
        snapshotsLoading,
        selectedSnapshot,
        hasChanges,
        unapprovedChangesCount,
        changedSnapshots,
    } = useValues(visualReviewRunSceneLogic)
    const { loadRun, loadSnapshots, setSelectedSnapshotId, approveChanges, approveSnapshot } =
        useActions(visualReviewRunSceneLogic)

    useEffect(() => {
        loadRun()
        loadSnapshots()
    }, [loadSnapshots, loadRun])

    if (runLoading || !run) {
        return <div className="p-4">Loading...</div>
    }

    // Count by result type
    const changedCount = snapshots.filter((s: SnapshotApi) => s.result === 'changed').length
    const newCount = snapshots.filter((s: SnapshotApi) => s.result === 'new').length
    const removedCount = snapshots.filter((s: SnapshotApi) => s.result === 'removed').length

    // Navigation within changed snapshots
    const currentIndex = selectedSnapshot
        ? changedSnapshots.findIndex((s: SnapshotApi) => s.id === selectedSnapshot.id)
        : -1
    const hasPrevious = currentIndex > 0
    const hasNext = currentIndex >= 0 && currentIndex < changedSnapshots.length - 1

    const goToPrevious = (): void => {
        if (hasPrevious) {
            setSelectedSnapshotId(changedSnapshots[currentIndex - 1].id)
        }
    }

    const goToNext = (): void => {
        if (hasNext) {
            setSelectedSnapshotId(changedSnapshots[currentIndex + 1].id)
        }
    }

    const handleApproveSnapshot = (): void => {
        if (selectedSnapshot) {
            approveSnapshot(selectedSnapshot)
        }
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={run.branch}
                resourceType={{ type: 'visual_review' }}
                actions={
                    hasChanges && unapprovedChangesCount > 0 ? (
                        <LemonButton type="primary" onClick={approveChanges}>
                            Approve {unapprovedChangesCount} change{unapprovedChangesCount !== 1 ? 's' : ''}
                        </LemonButton>
                    ) : undefined
                }
            />

            {/* Run metadata */}
            <div className="flex gap-4 items-center text-sm mb-4">
                <RunStatusBadge status={run.status} />
                <span className="font-mono">{run.commit_sha.substring(0, 7)}</span>
                {run.pr_number && <span>PR #{run.pr_number}</span>}
                {run.approved && <span className="text-success font-medium">✓ Approved</span>}
            </div>

            {/* Visual changes header + thumbnail strip */}
            {changedSnapshots.length > 0 && (
                <div className="mb-4">
                    <div className="flex items-center gap-4 mb-3">
                        <h3 className="font-semibold">Visual changes ({changedSnapshots.length})</h3>
                        <div className="text-sm text-muted">
                            {changedCount > 0 && <span className="text-warning-dark">{changedCount} changed</span>}
                            {newCount > 0 && <span className="text-primary-dark ml-2">{newCount} new</span>}
                            {removedCount > 0 && <span className="text-danger ml-2">{removedCount} removed</span>}
                        </div>
                    </div>

                    {/* Thumbnail strip */}
                    <div className="flex gap-4 overflow-x-auto py-3 px-2 -mx-2">
                        {changedSnapshots.map((snapshot: SnapshotApi) => (
                            <SnapshotThumbnail
                                key={snapshot.id}
                                snapshot={snapshot}
                                isSelected={selectedSnapshot?.id === snapshot.id}
                                onClick={() => setSelectedSnapshotId(snapshot.id)}
                            />
                        ))}
                    </div>
                </div>
            )}

            <LemonDivider />

            {/* Selected snapshot diff viewer */}
            <div className="mt-4">
                {selectedSnapshot ? (
                    <SnapshotDiffViewer
                        snapshot={selectedSnapshot}
                        onApprove={handleApproveSnapshot}
                        onPrevious={goToPrevious}
                        onNext={goToNext}
                        hasPrevious={hasPrevious}
                        hasNext={hasNext}
                        currentIndex={currentIndex >= 0 ? currentIndex : undefined}
                        totalCount={changedSnapshots.length}
                    />
                ) : snapshotsLoading ? (
                    <div className="text-center text-muted py-8">Loading snapshots...</div>
                ) : changedSnapshots.length > 0 ? (
                    <div className="text-center text-muted py-8">Select a snapshot to view details</div>
                ) : (
                    <div className="text-center text-muted py-8">No visual changes in this run</div>
                )}
            </div>
        </SceneContent>
    )
}

export default VisualReviewRunScene
