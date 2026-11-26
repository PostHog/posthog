import './NotebookAppBuilder.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useId, useMemo, useRef, useState } from 'react'

import { LemonBanner, LemonTabs, Spinner } from '@posthog/lemon-ui'

import { ApiConfig } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { cn } from 'lib/utils/css-classes'
import { objectsEqual } from 'lib/utils/objects'
import { urls } from 'scenes/urls'

import { notebooksAppComputeCreate, notebooksAppDraftComputeCreate } from '../generated/api'
import type { NotebookAppRefreshOutputsApiOutputs, NotebookAppReleaseApi } from '../generated/api.schemas'
import { WidgetFrameSessionContext } from '../NotebookNodeGeneratedWidget/widgetFrameSession'
import { NotebookAppCanvas } from './NotebookAppCanvas'
import { queryChoices, sqlChoiceSource } from './notebookAppChoices'
import { appSourceCells } from './notebookAppLayout'
import { savedQueryResult } from './notebookAppPublishedResults'
import { NotebookAppRefreshPanel } from './NotebookAppRefreshPanel'
import { resolveAppSelection } from './notebookAppSelection'
import { notebookAppViewerLogic, type ViewerProps } from './notebookAppViewerLogic'
import { PublishedNotebookAppControls } from './PublishedNotebookAppControls'
import { PublishedNotebookQuery } from './PublishedNotebookQuery'
import { ViewerComputeCell } from './ViewerComputeCell'
import { viewerWidgetSession } from './viewerWidgetFrames'

export default function PublishedNotebookApp({
    shortId,
    draft,
    initialInputs,
    initialTab,
}: {
    shortId: string
    draft?: NotebookAppReleaseApi
    initialInputs?: unknown
    initialTab?: unknown
}): JSX.Element {
    const project = String(ApiConfig.getCurrentTeamId())
    const sessionId = useId()
    const viewer = { project, shortId, sessionId, draft, initialInputs }
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
    return release ? (
        <AppSession key={release.revision} viewer={viewer} release={release} initialTab={initialTab} />
    ) : (
        <Spinner />
    )
}

function AppSession({
    viewer,
    release,
    initialTab,
}: {
    viewer: ViewerProps
    release: NotebookAppReleaseApi
    initialTab?: unknown
}): JSX.Element {
    const { shortId, sessionId } = viewer
    const { layout } = release
    const logic = notebookAppViewerLogic(viewer)
    const { variables, results, publishedResults, dirty, resultsLoading, refreshFailed: error } = useValues(logic)
    const { changeInput, changeInputs } = useActions(logic)
    const cells = useMemo(() => appSourceCells(release.markdown), [release.markdown])
    const [scheduled, setScheduled] = useState<NotebookAppRefreshOutputsApiOutputs>({})
    const [activeTab, setActiveTab] = useState(
        layout.tabs.find((tab) => tab.id === initialTab)?.id ?? layout.tabs[0]?.id ?? ''
    )
    const selectionSequence = useRef(0)
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
            <PublishedNotebookAppControls viewer={viewer} release={release} cells={cells} activeTab={activeTab} />
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
                value={(nodeId, versionId) => ({
                    ...viewerWidgetSession(results?.outputs ?? {}, nodeId, versionId),
                    privateInputs: versionId
                        ? {
                              key: JSON.stringify([release.revision, variables]),
                              compute: async (slot, signal) => {
                                  const request = {
                                      node_id: nodeId,
                                      revision: release.revision,
                                      variables,
                                      widget_input: { version_id: versionId, slot },
                                  }
                                  const result = viewer.draft
                                      ? await notebooksAppDraftComputeCreate(
                                            viewer.project,
                                            shortId,
                                            { ...request, layout },
                                            { signal }
                                        )
                                      : await notebooksAppComputeCreate(viewer.project, shortId, request, { signal })
                                  if (!result.widget_frame) {
                                      throw new Error('The calculation did not return a dataframe.')
                                  }
                                  return result.widget_frame
                              },
                          }
                        : undefined,
                })}
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
                    onInput={changeInputs}
                    getQueryChoices={(cell, column) => {
                        const attributes = sqlChoiceSource(cell)
                        if (!cell || !attributes) {
                            return null
                        }
                        const current = results?.outputs[cell.id]?.result
                        if (current) {
                            return queryChoices(current.columns, current.results, column, !!current.hasMore)
                        }
                        const saved = savedQueryResult(attributes, publishedResults[cell.id])
                        return saved && typeof saved === 'object'
                            ? queryChoices(
                                  saved.result.columns,
                                  saved.result.results,
                                  column,
                                  saved.rows !== 'complete'
                              )
                            : null
                    }}
                    renderOutput={(cell, block, saved) => {
                        if (cell.type !== 'component') {
                            return
                        }
                        const sql = cell.tagName === 'SQLV2'
                        const selection = block.selection
                        const select = async (row: Record<string, unknown>): Promise<void> => {
                            if (!selection) {
                                return
                            }
                            const sequence = ++selectionSequence.current
                            try {
                                const input = await resolveAppSelection(selection, row, variables)
                                if (!input || sequence !== selectionSequence.current || !logic.isMounted()) {
                                    return
                                }
                                changeInput(input.name, input.value)
                                if (selection.tab_id && layout.tabs.some((tab) => tab.id === selection.tab_id)) {
                                    setActiveTab(selection.tab_id)
                                }
                                posthog.capture('notebook app result selected', {
                                    short_id: shortId,
                                    conditional: !!selection.condition,
                                })
                            } catch {
                                lemonToast.error(
                                    'Could not apply the selection. Check the Hog condition in the app builder.'
                                )
                            }
                        }
                        const savedOutput = sql ? (
                            <PublishedNotebookQuery
                                block={block}
                                project={viewer.project}
                                pendingInputs={dirty || resultsLoading || error}
                                cell={cell}
                                sessionId={sessionId}
                                draft={!!viewer.draft}
                                current={results?.outputs[cell.id]}
                                pinned={publishedResults[cell.id]}
                                scheduled={scheduled[cell.id]}
                                chartInputFilters={
                                    selection
                                        ? { [selection.column]: (value) => void select({ [selection.column]: value }) }
                                        : chartInputFilters
                                }
                                onSelectResultRow={selection ? select : undefined}
                            />
                        ) : (
                            saved
                        )
                        if (
                            cell.tagName === 'PythonV2' ||
                            (sql &&
                                (cell.props.connectionId || (results && !results.nativeOutputIds.includes(cell.id))))
                        ) {
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
