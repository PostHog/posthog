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

import type { NotebookAppReleaseApi } from '../generated/api.schemas'
import { NotebookAppCanvas } from './NotebookAppCanvas'
import { appSourceCells } from './notebookAppLayout'
import { resolveAppSelection } from './notebookAppSelection'
import { notebookAppViewerLogic, type ViewerProps } from './notebookAppViewerLogic'
import { PublishedNotebookAppControls } from './PublishedNotebookAppControls'
import { PublishedNotebookQuery } from './PublishedNotebookQuery'

export default function PublishedNotebookApp({ shortId }: { shortId: string }): JSX.Element {
    const project = String(ApiConfig.getCurrentTeamId())
    const sessionId = useId()
    const viewer = { project, shortId, sessionId }
    const logic = notebookAppViewerLogic(viewer)
    const { release, releaseFailed: failed } = useValues(logic)
    const { loadRelease } = useActions(logic)
    if (failed) {
        return (
            <LemonBanner type="warning" action={{ children: 'Retry', onClick: loadRelease }}>
                Could not open the published app. Check that it is published and that you have access.
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
    const [activeTab, setActiveTab] = useState(layout.tabs[0]?.id || '')
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
            <PublishedNotebookAppControls viewer={viewer} release={release} cells={cells} />
            {results?.variables.some(
                (variable) =>
                    !objectsEqual(variable.value, release.variables.find((v) => v.name === variable.name)?.value)
            ) &&
                layout.blocks.some(
                    (block) =>
                        block.kind === 'cell' && block.display !== 'source' && !results.outputs[block.node_id || '']
                ) && (
                    <p className="text-secondary">
                        Filters apply to connected native SQL outputs. Other components show their published
                        configuration.
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
                renderOutput={(cell, block) => {
                    if (cell.type !== 'component' || cell.tagName !== 'SQLV2') {
                        return undefined
                    }
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
                    return (
                        <PublishedNotebookQuery
                            cell={cell}
                            sessionId={sessionId}
                            current={results?.outputs[cell.id]}
                            pinned={publishedResults[cell.id]}
                            chartInputFilters={
                                selection
                                    ? { [selection.column]: (value) => void select({ [selection.column]: value }) }
                                    : chartInputFilters
                            }
                            onSelectResultRow={selection ? select : undefined}
                        />
                    )
                }}
                onSource={(node) => router.actions.push(urls.notebook(shortId), {}, { node })}
            />
        </main>
    )
}
