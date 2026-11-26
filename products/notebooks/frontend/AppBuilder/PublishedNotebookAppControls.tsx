import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { Suspense, useState } from 'react'

import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'

import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { urls } from 'scenes/urls'

import type { NotebookAppReleaseApi } from '../generated/api.schemas'
import { notebookAppViewerLogic, type ViewerProps } from './notebookAppViewerLogic'
import { notebookAppViewPath } from './notebookAppViewLink'

const NotebookAppSavedViews = lazyWithRetry(() => import('./NotebookAppSavedViews'))

function SavedViewsButton({
    viewer,
    viewPath,
    dirty,
}: {
    viewer: ViewerProps
    viewPath: () => string
    dirty: boolean
}): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <>
            <LemonButton size="small" onClick={() => setOpen(true)}>
                Saved views
            </LemonButton>
            {open && (
                <Suspense fallback={null}>
                    <NotebookAppSavedViews
                        project={viewer.project}
                        shortId={viewer.shortId}
                        href={viewPath()}
                        dirty={dirty}
                        onClose={() => setOpen(false)}
                    />
                </Suspense>
            )}
        </>
    )
}

function ResultTimestamp({
    updatedAt,
    publishedAsOf,
}: {
    updatedAt?: string
    publishedAsOf: string | null
}): JSX.Element | null {
    if (updatedAt) {
        return <span role="status">Results updated {new Date(updatedAt).toLocaleTimeString()}</span>
    }
    return publishedAsOf ? (
        <span className="text-secondary">Oldest published result ran {new Date(publishedAsOf).toLocaleString()}</span>
    ) : null
}

export function PublishedNotebookAppControls({
    viewer,
    release,
    cells,
    activeTab,
}: {
    viewer: ViewerProps
    release: NotebookAppReleaseApi
    cells: NotebookBlockNode[]
    activeTab: string
}): JSX.Element {
    const { shortId } = viewer
    const { layout } = release
    const { canEditNotebook, isTemplate } = useValues(notebookLogic({ shortId }))
    const logic = notebookAppViewerLogic(viewer)
    const { variables, results, resultsLoading: busy, auto, dirty } = useValues(logic)
    const { setAuto, refresh } = useActions(logic)
    const viewPath = (): string => notebookAppViewPath(viewer.project, shortId, activeTab, variables)
    const hasNativeSql = cells.some(
        (cell) =>
            cell.type === 'component' &&
            cell.tagName === 'SQLV2' &&
            !cell.props.connectionId &&
            !cell.props.sendRawQuery &&
            layout.blocks.some((block) => block.node_id === cell.id && block.display !== 'source')
    )

    return (
        <div className="flex flex-wrap items-center gap-3 mb-4">
            <span className="text-secondary">
                {release.published_at
                    ? 'Published ' + new Date(release.published_at).toLocaleString()
                    : 'Published app'}
            </span>
            <ResultTimestamp updatedAt={results?.updatedAt} publishedAsOf={release.results_as_of} />
            <LemonButton size="small" to={urls.notebook(shortId)}>
                Open notebook
            </LemonButton>
            {canEditNotebook && !isTemplate && (
                <LemonButton size="small" to={urls.notebook(shortId) + '?view=builder'}>
                    App builder
                </LemonButton>
            )}
            <LemonButton
                size="small"
                disabledReason={dirty ? 'Apply your filters before copying this view.' : undefined}
                onClick={async () => {
                    if (await copyToClipboard(urls.absolute(viewPath()), 'view link')) {
                        posthog.capture('notebook app view link copied', {
                            short_id: shortId,
                            revision: release.revision,
                        })
                    }
                }}
            >
                Copy view link
            </LemonButton>
            <SavedViewsButton viewer={viewer} viewPath={viewPath} dirty={dirty} />
            {variables.length > 0 && <LemonCheckbox label="Auto-update results" checked={auto} onChange={setAuto} />}
            {(hasNativeSql || variables.length > 0) && (
                <LemonButton type="secondary" size="small" loading={busy} onClick={() => refresh(!dirty)}>
                    {dirty ? 'Apply filters' : 'Refresh results'}
                </LemonButton>
            )}
            {dirty && <span role="status">Filters pending</span>}
        </div>
    )
}
