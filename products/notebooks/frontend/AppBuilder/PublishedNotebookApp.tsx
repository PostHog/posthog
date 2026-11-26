import './NotebookAppBuilder.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useId, useMemo, useState } from 'react'

import { LemonBanner, LemonTabs, Spinner } from '@posthog/lemon-ui'

import { ApiConfig } from 'lib/api'
import { cn } from 'lib/utils/css-classes'
import { objectsEqual } from 'lib/utils/objects'
import { urls } from 'scenes/urls'

import type { NotebookAppRefreshOutputsApiOutputs, NotebookAppReleaseApi } from '../generated/api.schemas'
import { WidgetFrameSessionContext } from '../NotebookNodeGeneratedWidget/widgetFrameSession'
import { NotebookAppCanvas } from './NotebookAppCanvas'
import { appSourceCells } from './notebookAppLayout'
import { NotebookAppRefreshPanel } from './NotebookAppRefreshPanel'
import { notebookAppViewerLogic, type ViewerProps } from './notebookAppViewerLogic'
import { PublishedNotebookAppControls } from './PublishedNotebookAppControls'
import { PublishedNotebookQuery } from './PublishedNotebookQuery'
import { ViewerComputeCell } from './ViewerComputeCell'
import { viewerWidgetSession } from './viewerWidgetFrames'

export default function PublishedNotebookApp({
    shortId,
    draft,
}: {
    shortId: string
    draft?: NotebookAppReleaseApi
}): JSX.Element {
    const project = String(ApiConfig.getCurrentTeamId())
    const sessionId = useId()
    const viewer = { project, shortId, sessionId, draft }
    const logic = notebookAppViewerLogic(viewer)
    const { release, releaseFailed: failed } = useValues(logic)
    const { loadRelease } = useActions(logic)
    if (failed) {
        return (
            <LemonBanner type="warning" action={{ children: 'Retry', onClick: loadRelease }}>
                Could not open the app. Check that you have access and try again.
            </LemonBanner>
        )
    }
    return release ? <AppSession key={release.revision} viewer={viewer} release={release} /> : <Spinner />
}

function AppSession({ viewer, release }: { viewer: ViewerProps; release: NotebookAppReleaseApi }): JSX.Element {
    const { shortId, sessionId } = viewer
    const { layout } = release
    const logic = notebookAppViewerLogic(viewer)
    const { variables, results, publishedResults, refreshFailed: error } = useValues(logic)
    const { changeInput } = useActions(logic)
    const cells = useMemo(() => appSourceCells(release.markdown), [release.markdown])
    const [scheduled, setScheduled] = useState<NotebookAppRefreshOutputsApiOutputs>({})
    const [activeTab, setActiveTab] = useState(layout.tabs[0]?.id || '')
    const chartInputFilters = Object.fromEntries(
        variables.map((v) => [
            v.name,
            (value: unknown) => {
                if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
                    changeInput(v.name, v.type === 'list' ? [String(value)] : value)
                }
            },
        ])
    )

    return (
        <main
            className={cn('NotebookAppBuilder mt-4', !layout.full_width && 'NotebookAppBuilder__page')}
            data-attr="notebook-app-builder"
        >
            <h1>{layout.title || release.title || 'Untitled app'}</h1>
            {layout.description && <p>{layout.description}</p>}
            {!viewer.draft && (
                <NotebookAppRefreshPanel shortId={shortId} revision={release.revision} onOutputs={setScheduled} />
            )}
            <PublishedNotebookAppControls viewer={viewer} release={release} cells={cells} />
            {results?.variables.some(
                (variable) =>
                    !objectsEqual(variable.value, release.variables.find((v) => v.name === variable.name)?.value)
            ) &&
                layout.blocks.some(
                    (block) =>
                        block.kind === 'cell' &&
                        block.display !== 'source' &&
                        !results.outputs[block.node_id || ''] &&
                        !Object.values(results.outputs).some((output) =>
                            output.widgetSlots.some((slot) => slot.node_id === block.node_id)
                        )
                ) && (
                    <p className="text-secondary">
                        Filters update native SQL and its connected widgets. Run Python and connected queries to apply
                        your current inputs.
                    </p>
                )}
            {error && (
                <LemonBanner type="error" className="mb-3">
                    Could not update results. The last available results are still shown. Try again or reload the app
                    for the latest version.
                </LemonBanner>
            )}
            <LemonTabs
                activeKey={activeTab}
                onChange={setActiveTab}
                tabs={layout.tabs.map((tab) => ({ key: tab.id, label: tab.title }))}
            />
            <WidgetFrameSessionContext.Provider
                value={(nodeId, versionId) => viewerWidgetSession(results?.outputs ?? {}, nodeId, versionId)}
            >
                <NotebookAppCanvas
                    layout={layout}
                    activeTab={activeTab}
                    cells={cells}
                    staleNodeIds={{}}
                    variables={variables}
                    editing={false}
                    selectedId={null}
                    canInteract
                    onInput={changeInput}
                    renderOutput={(cell, saved) => {
                        if (cell.type !== 'component') {
                            return
                        }
                        const sql = cell.tagName === 'SQLV2'
                        const savedOutput = sql ? (
                            <PublishedNotebookQuery
                                cell={cell}
                                sessionId={sessionId}
                                draft={!!viewer.draft}
                                current={results?.outputs[cell.id]}
                                pinned={publishedResults[cell.id]}
                                scheduled={scheduled[cell.id]}
                                chartInputFilters={chartInputFilters}
                            />
                        ) : (
                            saved
                        )
                        if (cell.tagName === 'PythonV2' || (sql && cell.props.connectionId)) {
                            return (
                                <ViewerComputeCell
                                    key={cell.id}
                                    viewer={viewer}
                                    revision={release.revision}
                                    cell={cell}
                                    variables={variables}
                                    saved={savedOutput}
                                />
                            )
                        }
                        return sql ? savedOutput : undefined
                    }}
                    onSource={(node) => router.actions.push(urls.notebook(shortId), {}, { node })}
                />
            </WidgetFrameSessionContext.Provider>
        </main>
    )
}
