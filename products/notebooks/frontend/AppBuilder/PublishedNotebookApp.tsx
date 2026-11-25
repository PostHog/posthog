import './NotebookAppBuilder.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useId, useMemo, useState } from 'react'

import { LemonBanner, LemonTabs, Spinner } from '@posthog/lemon-ui'

import { ApiConfig } from 'lib/api'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import type { NotebookAppReleaseApi } from '../generated/api.schemas'
import { NotebookAppCanvas } from './NotebookAppCanvas'
import { appSourceCells } from './notebookAppLayout'
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
    const chartInputFilters = Object.fromEntries(
        variables.map((v) => [
            v.name,
            (value: unknown) => {
                if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
                    changeInput(v.name, value)
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
                (variable) => variable.value !== release.variables.find((v) => v.name === variable.name)?.value
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
                renderOutput={(cell) =>
                    cell.type === 'component' && cell.tagName === 'SQLV2' ? (
                        <PublishedNotebookQuery
                            cell={cell}
                            sessionId={sessionId}
                            current={results?.outputs[cell.id]}
                            pinned={publishedResults[cell.id]}
                            chartInputFilters={chartInputFilters}
                        />
                    ) : undefined
                }
                onSource={(node) => router.actions.push(urls.notebook(shortId), {}, { node })}
            />
        </main>
    )
}
