import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { urls } from 'scenes/urls'

import { fileSystemShortcutCreate, fileSystemShortcutDestroy } from '~/generated/core/api'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { escapePath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'

export default function NotebookAppSavedViews({
    project,
    shortId,
    href,
    dirty,
    onClose,
}: {
    project: string
    shortId: string
    href: string
    dirty: boolean
    onClose: () => void
}): JSX.Element {
    const { shortcutData, shortcutDataHasLoaded, shortcutDataLoading } = useValues(projectTreeDataLogic)
    const { loadShortcuts } = useActions(projectTreeDataLogic)
    const [name, setName] = useState('')
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState('')
    const prefix = urls.project(project, urls.notebook(shortId)) + '?view=app#appView='
    const views = shortcutData.filter((item) => item.href?.startsWith(prefix))
    const path = escapePath(name.trim())
    const disabledReason = dirty
        ? 'Apply your filters before saving this view.'
        : !path
          ? 'Enter a name for this view.'
          : views.some((view) => view.path === path)
            ? 'Choose a different name for this view.'
            : undefined

    async function save(): Promise<void> {
        if (disabledReason || busy) {
            return
        }
        setBusy(true)
        setError('')
        try {
            await fileSystemShortcutCreate(project, { path, type: 'notebook', href })
            setName('')
            loadShortcuts()
            posthog.capture('notebook app view saved', { short_id: shortId })
        } catch {
            setError('Could not save the view. Try again.')
        } finally {
            setBusy(false)
        }
    }

    async function remove(id: string): Promise<void> {
        setBusy(true)
        setError('')
        try {
            await fileSystemShortcutDestroy(project, id)
            loadShortcuts()
            posthog.capture('notebook app view removed', { short_id: shortId })
        } catch {
            setError('Could not remove the view. Try again.')
        } finally {
            setBusy(false)
        }
    }

    return (
        <LemonModal isOpen onClose={onClose} title="Saved views">
            <p>Save this tab and its applied filters to your starred items.</p>
            <form
                onSubmit={(event) => {
                    event.preventDefault()
                    void save()
                }}
            >
                <LemonLabel htmlFor="notebook-app-view-name">View name</LemonLabel>
                <div className="flex items-center gap-2 mt-1">
                    <LemonInput id="notebook-app-view-name" value={name} onChange={setName} fullWidth maxLength={120} />
                    <LemonButton
                        htmlType="submit"
                        type="primary"
                        disabledReason={disabledReason}
                        loading={busy || shortcutDataLoading}
                    >
                        Save view
                    </LemonButton>
                </div>
            </form>
            {error && (
                <div role="alert" className="text-danger mt-2">
                    {error}
                </div>
            )}
            <div className="mt-4">
                {views.length > 0 ? (
                    <ul className="list-none p-0 m-0 divide-y">
                        {views.map((view) => (
                            <li key={view.id} className="flex items-center justify-between gap-4 py-1">
                                <LemonButton
                                    to={view.href}
                                    targetBlank
                                    onClick={() =>
                                        posthog.capture('notebook app saved view opened', { short_id: shortId })
                                    }
                                >
                                    {unescapePath(view.path)}
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    status="danger"
                                    aria-label={`Remove ${unescapePath(view.path)}`}
                                    disabled={busy}
                                    onClick={() => void remove(view.id)}
                                >
                                    Remove
                                </LemonButton>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p className="text-secondary" role="status">
                        {shortcutDataHasLoaded ? 'No saved views for this app yet.' : 'Loading saved views…'}
                    </p>
                )}
            </div>
        </LemonModal>
    )
}
