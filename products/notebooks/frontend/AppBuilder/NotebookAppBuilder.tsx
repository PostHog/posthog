import './NotebookAppBuilder.scss'

import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonMenu, LemonTabs, Spinner } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { NotebookRunAllButton } from 'scenes/notebooks/Notebook/NotebookRunAllButton'
import { urls } from 'scenes/urls'

import { NotebookAppCanvas } from './NotebookAppCanvas'
import { NotebookAppInspector } from './NotebookAppInspector'
import { notebookAppLogic } from './notebookAppLogic'
import { NotebookAppPalette } from './NotebookAppPalette'

export function NotebookAppBuilder({
    shortId,
    published = false,
}: {
    shortId: string
    published?: boolean
}): JSX.Element {
    const logic = notebookAppLogic({ shortId })
    const {
        layout,
        savedNotebook,
        savedNotebookLoading,
        error,
        preview,
        activeTabId,
        selectedBlock,
        selectedBlockId,
        cells,
        variables,
        canEditNotebook,
        isTemplate,
        dirty,
        history,
        notebook,
    } = useValues(logic)
    const {
        changeLayout,
        selectBlock,
        selectTab,
        setPreview,
        addBlock,
        addCell,
        updateBlock,
        removeBlock,
        duplicateBlock,
        moveBlock,
        moveBlockBy,
        addTab,
        removeTab,
        useNotebookLayout,
        undo,
        redo,
        setInputValue,
        openSource,
        saveApp,
        loadApp,
        unpublishApp,
    } = useActions(logic)
    const displayedLayout = published ? savedNotebook?.app_published : layout
    const editing = !published && !preview && canEditNotebook && !isTemplate
    const selectedTab = displayedLayout?.tabs.some((tab) => tab.id === activeTabId)
        ? activeTabId
        : (displayedLayout?.tabs[0]?.id ?? '')
    if (!savedNotebook && savedNotebookLoading) {
        return (
            <div className="p-8">
                <Spinner />
            </div>
        )
    }
    if (!savedNotebook) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadApp }}>
                {error || 'Could not load the app builder. Try again.'}
            </LemonBanner>
        )
    }
    if (!displayedLayout) {
        return (
            <LemonBanner type="info">
                This notebook has no published app. Open the app builder to create one.
            </LemonBanner>
        )
    }
    return (
        <div className="NotebookAppBuilder mt-4" data-attr="notebook-app-builder">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
                <div className="flex flex-wrap items-center gap-2">
                    <h2 className="m-0">{published ? 'App' : 'App builder'}</h2>
                    {!published && (
                        <span className="text-secondary text-xs">
                            {dirty ? 'Unsaved changes' : savedNotebook.app_draft ? 'Draft saved' : 'New app'}
                        </span>
                    )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    {canEditNotebook && !isTemplate && !published && (
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => setPreview(!preview)}
                                data-attr="notebook-app-preview"
                            >
                                {preview ? 'Back to builder' : 'Preview'}
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                size="small"
                                loading={savedNotebookLoading}
                                onClick={() => saveApp(false)}
                                disabledReason={!dirty ? 'No unsaved changes' : undefined}
                                data-attr="notebook-app-save"
                            >
                                Save draft
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                size="small"
                                loading={savedNotebookLoading}
                                onClick={() => saveApp(true)}
                                data-attr="notebook-app-publish"
                            >
                                {savedNotebook.app_published ? 'Publish changes' : 'Publish layout'}
                            </LemonButton>
                        </>
                    )}
                    <LemonMenu
                        items={[
                            {
                                label: 'Copy app link',
                                disabledReason: !savedNotebook.app_published ? 'Publish a layout first' : undefined,
                                onClick: () =>
                                    void copyToClipboard(
                                        `${window.location.origin}${urls.notebook(shortId)}?view=app`,
                                        'App link'
                                    ),
                            },
                            ...(!published && canEditNotebook && !isTemplate
                                ? [
                                      {
                                          label: 'Undo',
                                          disabledReason:
                                              !history.past.length || savedNotebookLoading
                                                  ? 'Nothing to undo'
                                                  : undefined,
                                          onClick: undo,
                                      },
                                      {
                                          label: 'Redo',
                                          disabledReason:
                                              !history.future.length || savedNotebookLoading
                                                  ? 'Nothing to redo'
                                                  : undefined,
                                          onClick: redo,
                                      },
                                      { label: 'App settings', onClick: () => selectBlock(null) },
                                      {
                                          label: 'Unpublish',
                                          status: 'danger' as const,
                                          disabledReason:
                                              !savedNotebook.app_published || savedNotebookLoading
                                                  ? 'No published app'
                                                  : undefined,
                                          onClick: unpublishApp,
                                      },
                                  ]
                                : []),
                        ]}
                    >
                        <LemonButton size="small" aria-label="More app actions">
                            •••
                        </LemonButton>
                    </LemonMenu>
                </div>
            </div>
            {error && (
                <LemonBanner type="error" className="mb-4">
                    {error}
                </LemonBanner>
            )}
            <fieldset disabled={savedNotebookLoading} className="border-0 p-0 m-0 min-w-0">
                <div className={editing ? 'NotebookAppBuilder__workspace' : ''}>
                    {editing && (
                        <NotebookAppPalette
                            cells={cells}
                            variables={variables}
                            onAdd={addBlock}
                            onAddCell={addCell}
                            onUseNotebook={useNotebookLayout}
                        />
                    )}
                    <main className={cn('min-w-0', !displayedLayout.full_width && 'NotebookAppBuilder__page')}>
                        <div className="mb-4">
                            <h1 className="mb-2">{displayedLayout.title || notebook?.title || 'Untitled app'}</h1>
                            {displayedLayout.description && (
                                <p className="text-secondary">{displayedLayout.description}</p>
                            )}
                            {!editing && canEditNotebook && !isTemplate && (
                                <NotebookRunAllButton type="secondary" size="small" />
                            )}
                        </div>
                        <div className="flex flex-wrap items-center gap-2 mb-4">
                            <LemonTabs
                                activeKey={selectedTab}
                                onChange={selectTab}
                                tabs={displayedLayout.tabs.map((tab) => ({ key: tab.id, label: tab.title }))}
                            />
                            {editing && (
                                <LemonMenu
                                    items={[
                                        {
                                            label: 'Add tab',
                                            icon: <IconPlus />,
                                            disabledReason: layout.tabs.length >= 20 ? 'Maximum 20 tabs' : undefined,
                                            onClick: addTab,
                                        },
                                        {
                                            label: 'Remove tab',
                                            status: 'danger',
                                            disabledReason:
                                                layout.tabs.length <= 1 ? 'Keep at least one tab' : undefined,
                                            onClick: () => removeTab(selectedTab),
                                        },
                                    ]}
                                >
                                    <LemonButton size="xsmall" aria-label="Tab actions">
                                        •••
                                    </LemonButton>
                                </LemonMenu>
                            )}
                        </div>
                        {editing && (
                            <LemonInput
                                className="mb-4"
                                size="small"
                                aria-label="Tab name"
                                value={layout.tabs.find((tab) => tab.id === selectedTab)?.title ?? ''}
                                maxLength={80}
                                onChange={(title) =>
                                    changeLayout({
                                        ...layout,
                                        tabs: layout.tabs.map((tab) =>
                                            tab.id === selectedTab ? { ...tab, title } : tab
                                        ),
                                    })
                                }
                            />
                        )}
                        <NotebookAppCanvas
                            layout={displayedLayout}
                            activeTab={selectedTab}
                            cells={cells}
                            variables={variables}
                            editing={editing}
                            selectedId={selectedBlockId}
                            canInteract={canEditNotebook && !isTemplate}
                            onSelect={selectBlock}
                            onMove={moveBlock}
                            onMoveBy={moveBlockBy}
                            onDuplicate={duplicateBlock}
                            onRemove={removeBlock}
                            onSource={openSource}
                            onInput={setInputValue}
                        />
                    </main>
                    {editing && (
                        <NotebookAppInspector
                            layout={layout}
                            block={selectedBlock}
                            cells={cells}
                            variables={variables}
                            onLayout={changeLayout}
                            onBlock={updateBlock}
                            onClose={() => selectBlock(null)}
                            onSource={openSource}
                        />
                    )}
                </div>
            </fieldset>
        </div>
    )
}
