import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { DashboardWidgetComponentProps } from 'products/dashboards/frontend/widgets/registry'

import { notebooksWidgetSnapshotFrame } from '../generated/api'
import { NotebookWidgetTrustControls } from '../NotebookNodeGeneratedWidget/NotebookWidgetTrustControls'
import {
    getNotebookWidgetTrust,
    notebookWidgetTrustLogic,
} from '../NotebookNodeGeneratedWidget/notebookWidgetTrustLogic'
import { WidgetArtifactFrame } from '../NotebookNodeGeneratedWidget/WidgetArtifactFrame'
import { applyReusableWidgetBinding, getReusableWidgetInputBinding } from '../ReusableWidget/reusableWidgetBindings'
import { NotebookDashboardWidgetProps, notebookDashboardWidgetLogic } from './notebookDashboardWidgetLogic'

export function NotebookDashboardWidget({
    tileId,
    config,
    onConfigPublished,
}: DashboardWidgetComponentProps): JSX.Element {
    if (typeof config.notebookShortId !== 'string' || typeof config.snapshotId !== 'string') {
        return <NotebookWidgetPreview />
    }
    return (
        <SavedNotebookWidget
            tileId={tileId}
            notebookShortId={config.notebookShortId}
            snapshotId={config.snapshotId}
            onSnapshotPublished={onConfigPublished}
        />
    )
}

export function NotebookWidgetPreview(): JSX.Element {
    return (
        <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 p-4 text-center">
            <strong>Bring notebook results to your dashboard</strong>
            <span className="text-secondary">
                Open a generated widget's menu in a notebook and choose Add to dashboard.
            </span>
            <LemonButton to={urls.notebooks()} size="small">
                Open notebooks
            </LemonButton>
        </div>
    )
}

function SavedNotebookWidget(props: NotebookDashboardWidgetProps): JSX.Element {
    const logic = notebookDashboardWidgetLogic(props)
    const { snapshot, snapshotLoading, error, runId, polling, progress, sourceOpen, sourceLoading, source } =
        useValues(logic)
    const { loadSnapshot, pollRun, setError, setSourceOpen } = useActions(logic)
    const { user } = useValues(userLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { sessionBuildHashes, trustByUser } = useValues(notebookWidgetTrustLogic)
    const { trustBuild } = useActions(notebookWidgetTrustLogic)
    const trusted = getNotebookWidgetTrust({
        sessionBuildHashes,
        trustByUser,
        userId: user?.id ?? null,
        buildHash: snapshot?.build_hash ?? null,
    }).buildTrusted
    const canRender = trusted || (snapshot?.security_review?.severity === 'none' && snapshot.frame_names.length === 0)

    return (
        <div className="flex h-full min-h-0 flex-col">
            {progress ? (
                <div className="p-2 text-secondary text-sm" role="status">
                    {progress}
                    <div>Keep this dashboard open until the refresh finishes.</div>
                </div>
            ) : null}
            {error ? (
                <LemonBanner
                    type="warning"
                    className="m-2"
                    action={{
                        children: runId ? 'Check run' : 'Reload saved results',
                        onClick: runId ? pollRun : loadSnapshot,
                        loading: polling || snapshotLoading,
                    }}
                >
                    {error}
                </LemonBanner>
            ) : null}
            {snapshotLoading && !snapshot ? <div className="p-4 text-secondary">Loading saved results…</div> : null}
            {snapshot && !snapshot.artifact_url ? (
                <div className="p-4 text-secondary">
                    This widget's build is unavailable. Open the notebook to check it.
                </div>
            ) : null}
            {snapshot?.artifact_url ? (
                <>
                    {!canRender ? (
                        <NotebookWidgetTrustControls
                            variant="gate"
                            buildHash={snapshot.build_hash}
                            securityReview={snapshot.security_review}
                            isEditable={false}
                            onRun={() => {
                                if (snapshot.build_hash) {
                                    trustBuild(user?.id ?? null, snapshot.build_hash)
                                }
                            }}
                            onViewSource={() => setSourceOpen(true)}
                        />
                    ) : null}
                    {canRender ? (
                        <div className="relative min-h-0 flex-1 overflow-hidden">
                            <WidgetArtifactFrame
                                key={snapshot.id}
                                artifactUrl={snapshot.artifact_url}
                                title="Saved notebook widget"
                                allowedFrames={snapshot.frame_names}
                                onReadFrame={async (name, offset, limit, _runId, signal) => {
                                    const frame = await notebooksWidgetSnapshotFrame(
                                        String(currentTeamId),
                                        props.notebookShortId,
                                        snapshot.id,
                                        name,
                                        { offset, limit },
                                        { signal }
                                    )
                                    return applyReusableWidgetBinding(
                                        frame,
                                        name,
                                        getReusableWidgetInputBinding(snapshot.input_bindings, name),
                                        snapshot.input_contract
                                            .find((input) => input.slot === name)
                                            ?.columns?.map((column) => column.name) ?? []
                                    )
                                }}
                                onArtifactUnavailable={() =>
                                    setError('The widget preview did not load. Reload the saved results to try again.')
                                }
                                onError={(message) =>
                                    setError(
                                        message ||
                                            'The widget could not display its saved results. Open the notebook to check it.'
                                    )
                                }
                            />
                        </div>
                    ) : null}
                </>
            ) : null}
            <LemonModal isOpen={sourceOpen} title="Widget source" onClose={() => setSourceOpen(false)} width={800}>
                {sourceLoading ? (
                    <p>Loading source…</p>
                ) : (
                    <pre className="ph-no-capture max-h-96 overflow-auto whitespace-pre-wrap break-words">{source}</pre>
                )}
            </LemonModal>
        </div>
    )
}
