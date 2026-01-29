import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonTab, LemonTabs, Tooltip } from '@posthog/lemon-ui'

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

type SnapshotFilter = 'changed' | 'new' | 'removed' | 'unchanged' | 'all'

function SnapshotCard({
    snapshot,
    isSelected,
    onClick,
}: {
    snapshot: SnapshotApi
    isSelected: boolean
    onClick: () => void
}): JSX.Element {
    const isApproved = !!snapshot.approved_at
    const hasChanges = snapshot.result === 'changed' || snapshot.result === 'new' || snapshot.result === 'removed'
    const displayResult = isApproved && hasChanges ? 'approved' : snapshot.result

    const resultStyles: Record<string, string> = {
        unchanged: 'border-border bg-bg-light text-muted',
        changed: 'border-warning bg-warning-highlight text-warning-dark',
        new: 'border-primary bg-primary-highlight text-primary-dark',
        removed: 'border-danger bg-danger-highlight text-danger-dark',
        approved: 'border-success bg-success-highlight text-success-dark',
    }

    const resultLabels: Record<string, string> = {
        unchanged: 'Unchanged',
        changed: 'Changed',
        new: 'New',
        removed: 'Removed',
        approved: 'Approved',
    }

    const shortName = snapshot.identifier.split('--').pop() || snapshot.identifier

    return (
        <button
            type="button"
            onClick={onClick}
            className={`
                flex flex-col items-center gap-1 p-2 rounded border-2 transition-all min-w-[100px] max-w-[140px] shrink-0
                ${resultStyles[displayResult] || resultStyles.unchanged}
                ${isSelected ? 'ring-2 ring-primary ring-offset-2' : 'hover:scale-105'}
            `}
        >
            <div className="w-16 h-12 bg-bg-3000 rounded flex items-center justify-center overflow-hidden">
                {snapshot.current_artifact?.download_url ? (
                    <img src={snapshot.current_artifact.download_url} alt="" className="w-full h-full object-cover" />
                ) : (
                    <span className="text-xs text-muted">No image</span>
                )}
            </div>
            <Tooltip title={snapshot.identifier}>
                <span className="text-xs font-medium truncate w-full text-center">{shortName}</span>
            </Tooltip>
            <span className="text-[10px] font-semibold uppercase flex items-center gap-0.5">
                {resultLabels[displayResult]}
                {isApproved && <IconCheck className="w-3 h-3" />}
            </span>
        </button>
    )
}

export function VisualReviewRunScene(): JSX.Element {
    const { run, runLoading, snapshots, snapshotsLoading, selectedSnapshot, hasChanges, unapprovedChangesCount } =
        useValues(visualReviewRunSceneLogic)
    const { loadRun, loadSnapshots, setSelectedSnapshotId, approveChanges } = useActions(visualReviewRunSceneLogic)
    const [activeTab, setActiveTab] = useState<SnapshotFilter>('changed')

    useEffect(() => {
        loadRun()
        loadSnapshots()
    }, [loadSnapshots, loadRun])

    // Auto-select first tab with content
    useEffect(() => {
        if (snapshots.length > 0) {
            const changed = snapshots.filter((s) => s.result === 'changed')
            const newSnaps = snapshots.filter((s) => s.result === 'new')
            const removed = snapshots.filter((s) => s.result === 'removed')

            if (changed.length > 0) {
                setActiveTab('changed')
            } else if (newSnaps.length > 0) {
                setActiveTab('new')
            } else if (removed.length > 0) {
                setActiveTab('removed')
            } else {
                setActiveTab('unchanged')
            }
        }
    }, [snapshots.length, snapshots])

    if (runLoading || !run) {
        return <div className="p-4">Loading...</div>
    }

    // Group snapshots
    const counts = {
        changed: snapshots.filter((s) => s.result === 'changed').length,
        new: snapshots.filter((s) => s.result === 'new').length,
        removed: snapshots.filter((s) => s.result === 'removed').length,
        unchanged: snapshots.filter((s) => s.result === 'unchanged').length,
        all: snapshots.length,
    }

    const filteredSnapshots = activeTab === 'all' ? snapshots : snapshots.filter((s) => s.result === activeTab)

    // Build tabs - only show tabs that have content (except 'all' which always shows)
    const tabs: LemonTab<SnapshotFilter>[] = []

    if (counts.changed > 0) {
        tabs.push({ key: 'changed', label: `Changed (${counts.changed})` })
    }
    if (counts.new > 0) {
        tabs.push({ key: 'new', label: `New (${counts.new})` })
    }
    if (counts.removed > 0) {
        tabs.push({ key: 'removed', label: `Removed (${counts.removed})` })
    }
    if (counts.unchanged > 0) {
        tabs.push({ key: 'unchanged', label: `Unchanged (${counts.unchanged})` })
    }
    // Always show "All" if there are multiple categories
    if (tabs.length > 1) {
        tabs.push({ key: 'all', label: `All (${counts.all})` })
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

            <div className="flex gap-4 items-center text-sm mb-4">
                <RunStatusBadge status={run.status} />
                <span className="font-mono">{run.commit_sha.substring(0, 7)}</span>
                {run.pr_number && <span>PR #{run.pr_number}</span>}
                {run.approved && <span className="text-success font-medium">✓ Approved</span>}
            </div>

            {/* Tabs for filtering */}
            {tabs.length > 0 && <LemonTabs activeKey={activeTab} onChange={(key) => setActiveTab(key)} tabs={tabs} />}

            {/* Snapshot cards */}
            {filteredSnapshots.length > 0 ? (
                <div className="flex gap-2 overflow-x-auto py-4">
                    {filteredSnapshots.map((snapshot) => (
                        <SnapshotCard
                            key={snapshot.id}
                            snapshot={snapshot}
                            isSelected={selectedSnapshot?.id === snapshot.id}
                            onClick={() => setSelectedSnapshotId(snapshot.id)}
                        />
                    ))}
                </div>
            ) : snapshotsLoading ? (
                <div className="text-center text-muted py-8">Loading snapshots...</div>
            ) : (
                <div className="text-center text-muted py-8">No snapshots in this category</div>
            )}

            <LemonDivider />

            {/* Selected snapshot diff viewer */}
            <div className="mt-4">
                {selectedSnapshot ? (
                    <SnapshotDiffViewer snapshot={selectedSnapshot} />
                ) : snapshots.length > 0 ? (
                    <div className="text-center text-muted py-8">Select a snapshot to view details</div>
                ) : null}
            </div>
        </SceneContent>
    )
}

export default VisualReviewRunScene
