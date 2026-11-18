import { useValues } from 'kea'
import { router } from 'kea-router'

import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { urls } from 'scenes/urls'

import { useAttachedContext, useComposerOverride, useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { notebookAppLogic } from './notebookAppLogic'

const APP_COMPOSER = {
    placeholder: 'Ask AI to build or change this app…',
    hideRepositorySelector: true,
}

export function NotebookAppAgentIntegration({ shortId }: { shortId: string }): null {
    const source = notebookLogic({ shortId })
    const { notebook, localContent, notebookLoading, canEditNotebook, isTemplate } = useValues(source)
    const dismissGroup = `notebook-app:${shortId}`
    useAttachedContext([
        { type: 'notebook', key: shortId, label: notebook?.title || 'Notebook', dismissGroup },
        {
            type: 'instructions',
            key: 'notebook-app-builder',
            label: 'App builder',
            value: 'For requests to build or edit an app from this notebook, read the building-notebook-apps skill. Use notebooks-get for source cells and variables and notebooks-app-get for layouts and revision. Carry the request through to a saved app with notebooks-app-update. If attached editor state reports unsaved changes, ask the user to save those before editing that resource. Do not publish unless asked. App tool completions refresh the open builder.',
            dismissGroup,
        },
        {
            type: 'notebook-editor-state',
            key: shortId,
            value: JSON.stringify({
                has_unsaved_notebook_changes: localContent !== null,
                notebook_saving: notebookLoading,
                read_only: !canEditNotebook || isTemplate,
            }),
            hidden: true,
            dismissGroup,
        },
    ])
    useMcpToolApplyBack({
        tools: ['notebooks-app-update'],
        targetKey: dismissGroup,
        onApply: (event, { innerInput }) => {
            if (innerInput?.short_id !== shortId || event.invocation.error) {
                return
            }
            const app = notebookAppLogic({ shortId })
            if (app.isMounted()) {
                app.actions.refreshFromAgent()
            }
            if (source.values.localContent === null && !source.values.notebookLoading) {
                source.actions.loadNotebook()
            }
            if (!app.isMounted() && source.values.canEditNotebook && !source.values.isTemplate) {
                router.actions.push(urls.notebook(shortId), { view: 'builder' })
            }
        },
    })
    return null
}

export function NotebookAppEditorAgentContext({ shortId }: { shortId: string }): null {
    useComposerOverride(APP_COMPOSER)
    const { dirty, savedNotebookLoading, selectedBlockId, activeTabId } = useValues(notebookAppLogic({ shortId }))
    useAttachedContext([
        {
            type: 'notebook-app-editor-state',
            key: shortId,
            value: JSON.stringify({
                has_unsaved_app_changes: dirty,
                app_saving: savedNotebookLoading,
                selected_block_id: selectedBlockId,
                active_tab_id: activeTabId,
            }),
            hidden: true,
            dismissGroup: `notebook-app:${shortId}`,
        },
    ])
    return null
}
