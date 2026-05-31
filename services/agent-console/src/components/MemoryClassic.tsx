/**
 * `<MemoryClassic>` — memory tab content. File-explorer-style: tree
 * + search on the left, reader / editor on the right. Mirrors
 * `<BundleTree>` chrome so navigating the agent's bundle and its
 * memory store feel like the same surface.
 *
 * Memory is editable. The right pane swaps between a read-only
 * viewer (with Edit / Delete / Rendered-Raw toggle) and an inline
 * editor for create / update. A "+ New memory" action sits above
 * the tree.
 */

'use client'

import { PencilIcon, PlusIcon, Trash2Icon } from 'lucide-react'
import { useCallback, useState } from 'react'

import { Markdown } from '@posthog/agent-chat'

import { useSessionTeamId } from '@/components/session-context'
import {
    createMemoryFile,
    deleteMemoryFile,
    getMemoryTree,
    readMemoryFile,
    searchMemoryApi,
    updateMemoryFile,
    type MemoryFile,
    type MemoryTreeNode,
} from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'

import { FileExplorer, type FileExplorerSearchResult, type FileTreeNode } from './FileExplorer'
import { RefreshIndicator } from './RefreshIndicator'

const NEW_FILE_SENTINEL = '__new__'

type ViewMode = 'rendered' | 'raw'

interface DraftState {
    /** Empty for new file, original path for edits. */
    path: string
    description: string
    content: string
    tags: string[]
    isNew: boolean
}

interface MemoryClassicProps {
    slug: string
}

export function MemoryClassic({ slug }: MemoryClassicProps): React.ReactElement {
    const teamId = useSessionTeamId()!

    const [selectedPath, setSelectedPath] = useState<string | null>(null)
    const [query, setQuery] = useState('')
    const [draft, setDraft] = useState<DraftState | null>(null)

    const tree = useResource(() => getMemoryTree(teamId, slug), [teamId, slug])
    const search = useResource(
        () => (query.trim() ? searchMemoryApi(teamId, slug, query.trim()) : Promise.resolve(null)),
        [teamId, slug, query]
    )

    // Active file is what the reader pane should fetch. The "__new__"
    // sentinel + the draft state together drive editor mode.
    const isEditingExisting = !!draft && !draft.isNew
    const activeFilePath =
        draft?.isNew || selectedPath === NEW_FILE_SENTINEL ? null : isEditingExisting ? null : selectedPath

    const file = useResource(
        () => (activeFilePath ? readMemoryFile(teamId, slug, activeFilePath) : Promise.resolve(null)),
        [teamId, slug, activeFilePath]
    )

    const onSelect = useCallback((path: string) => {
        setDraft(null)
        setSelectedPath(path)
    }, [])

    const startNew = useCallback(() => {
        setDraft({ path: '', description: '', content: '', tags: [], isNew: true })
        setSelectedPath(NEW_FILE_SENTINEL)
    }, [])

    const startEdit = useCallback((f: MemoryFile) => {
        setDraft({ path: f.path, description: f.description, content: f.content, tags: f.tags, isNew: false })
    }, [])

    const cancelDraft = useCallback(() => {
        if (draft?.isNew) {
            setSelectedPath(null)
        }
        setDraft(null)
    }, [draft])

    const saveDraft = useCallback(
        async (next: DraftState): Promise<void> => {
            if (next.isNew) {
                const saved = await createMemoryFile(teamId, slug, {
                    path: next.path,
                    description: next.description,
                    content: next.content,
                    tags: next.tags,
                })
                setDraft(null)
                setSelectedPath(saved.path)
                tree.reload()
            } else {
                const saved = await updateMemoryFile(teamId, slug, next.path, {
                    description: next.description,
                    content: next.content,
                    tags: next.tags,
                })
                setDraft(null)
                setSelectedPath(saved.path)
                tree.reload()
            }
        },
        [teamId, slug, tree]
    )

    const deleteFile = useCallback(
        async (path: string): Promise<void> => {
            if (!confirm(`Delete ${path}? This cannot be undone.`)) {
                return
            }
            try {
                await deleteMemoryFile(teamId, slug, path)
                if (selectedPath === path) {
                    setSelectedPath(null)
                }
                tree.reload()
            } catch (err) {
                alert(`Delete failed: ${(err as Error).message}`)
            }
        },
        [teamId, slug, selectedPath, tree]
    )

    const treeRoot: FileTreeNode | null = tree.data?.root ? toFileTreeNode(tree.data.root) : null
    const searchResults: FileExplorerSearchResult[] | null = query.trim()
        ? (search.data?.results ?? []).map((r) => ({
              path: r.path,
              name: r.path,
              description: r.description ?? undefined,
              snippet: r.snippet ?? undefined,
              score: r.score,
          }))
        : null

    return (
        <FileExplorer
            storageKey="file-explorer:memory"
            tree={treeRoot}
            selectedPath={selectedPath}
            onSelectPath={onSelect}
            search={{
                query,
                onChange: setQuery,
                results: searchResults,
                placeholder: 'Search memory…',
                loading: search.loading,
            }}
            topAction={
                <button
                    type="button"
                    onClick={startNew}
                    disabled={!!draft}
                    className="inline-flex h-7 w-full cursor-pointer items-center justify-center gap-1 rounded border border-border bg-card text-xs font-medium hover:bg-accent disabled:opacity-50"
                >
                    <PlusIcon className="h-3 w-3" />
                    New memory
                </button>
            }
            emptyMessage="No memory yet. Use “+ New memory” to write one."
            loading={tree.loading && !tree.data}
            error={tree.error}
        >
            {draft ? (
                <MemoryEditor initial={draft} onSave={saveDraft} onCancel={cancelDraft} />
            ) : selectedPath && selectedPath !== NEW_FILE_SENTINEL ? (
                <MemoryReader
                    file={file.data}
                    loading={file.loading}
                    error={file.error}
                    fileResource={file}
                    onEdit={startEdit}
                    onDelete={(path) => void deleteFile(path)}
                />
            ) : (
                <EmptyState />
            )}
        </FileExplorer>
    )
}

function toFileTreeNode(node: MemoryTreeNode): FileTreeNode {
    return {
        type: node.type,
        name: node.name,
        path: node.path,
        description: node.description ?? undefined,
        children: node.children?.map(toFileTreeNode),
    }
}

function EmptyState(): React.ReactElement {
    return (
        <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
            Pick a memory file on the left, or click “+ New memory” to write one.
        </div>
    )
}

function MemoryReader({
    file,
    loading,
    error,
    fileResource,
    onEdit,
    onDelete,
}: {
    file: MemoryFile | null
    loading: boolean
    error: Error | null
    fileResource: ReturnType<typeof useResource<MemoryFile | null>>
    onEdit: (file: MemoryFile) => void
    onDelete: (path: string) => void
}): React.ReactElement {
    const [viewMode, setViewMode] = useState<ViewMode>('rendered')

    if (loading && !file) {
        return <div className="p-6 text-sm text-muted-foreground">Loading…</div>
    }
    if (error) {
        return <div className="p-6 text-sm text-destructive-foreground">Failed to load: {error.message}</div>
    }
    if (!file) {
        return <EmptyState />
    }
    return (
        <div className="flex h-full flex-col">
            <header className="flex items-start justify-between gap-3 border-b border-border bg-muted/10 px-3 py-2">
                <div className="min-w-0 flex-1">
                    <code className="block truncate text-[0.8125rem] font-mono">{file.path}</code>
                    {file.description ? (
                        <p className="mt-0.5 text-xs text-muted-foreground">{file.description}</p>
                    ) : null}
                    {file.tags.length > 0 ? (
                        <div className="mt-1 flex flex-wrap gap-1">
                            {file.tags.map((t) => (
                                <span
                                    key={t}
                                    className="rounded bg-muted px-1.5 py-0.5 text-[0.625rem] text-muted-foreground"
                                >
                                    {t}
                                </span>
                            ))}
                        </div>
                    ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                    <RefreshIndicator resource={fileResource} intervalMs={0} />
                    <div className="flex overflow-hidden rounded border border-border text-[0.625rem]">
                        <button
                            type="button"
                            onClick={() => setViewMode('rendered')}
                            aria-pressed={viewMode === 'rendered'}
                            className={`px-1.5 py-0.5 ${viewMode === 'rendered' ? 'bg-muted font-medium' : 'hover:bg-muted'}`}
                        >
                            Rendered
                        </button>
                        <button
                            type="button"
                            onClick={() => setViewMode('raw')}
                            aria-pressed={viewMode === 'raw'}
                            className={`border-l border-border px-1.5 py-0.5 ${viewMode === 'raw' ? 'bg-muted font-medium' : 'hover:bg-muted'}`}
                        >
                            Raw
                        </button>
                    </div>
                    <button
                        type="button"
                        onClick={() => onEdit(file)}
                        className="inline-flex h-6 cursor-pointer items-center gap-1 rounded border border-border bg-card px-2 text-[0.6875rem] hover:bg-accent"
                    >
                        <PencilIcon className="h-2.5 w-2.5" />
                        Edit
                    </button>
                    <button
                        type="button"
                        onClick={() => onDelete(file.path)}
                        className="inline-flex h-6 cursor-pointer items-center gap-1 rounded border border-destructive-foreground/40 px-2 text-[0.6875rem] text-destructive-foreground hover:bg-destructive/10"
                    >
                        <Trash2Icon className="h-2.5 w-2.5" />
                        Delete
                    </button>
                </div>
            </header>
            <div className="min-h-0 flex-1 overflow-auto p-3">
                {viewMode === 'rendered' ? (
                    <Markdown>{file.content}</Markdown>
                ) : (
                    <pre className="whitespace-pre-wrap break-words font-mono text-[0.75rem] leading-relaxed">
                        {file.content}
                    </pre>
                )}
            </div>
        </div>
    )
}

function MemoryEditor({
    initial,
    onSave,
    onCancel,
}: {
    initial: DraftState
    onSave: (next: DraftState) => Promise<void>
    onCancel: () => void
}): React.ReactElement {
    const [state, setState] = useState<DraftState>(initial)
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const patch = (next: Partial<DraftState>): void => setState((s) => ({ ...s, ...next }))

    const submit = async (): Promise<void> => {
        if (!state.description.trim()) {
            setError('Description is required.')
            return
        }
        if (state.description.length > 280) {
            setError('Description must be ≤ 280 characters.')
            return
        }
        if (state.isNew && !/^[a-z0-9][a-z0-9_/-]*\.md$/.test(state.path)) {
            setError("Path must be lowercase a-z 0-9 _ - / only and end in '.md'.")
            return
        }
        setSaving(true)
        setError(null)
        try {
            await onSave(state)
        } catch (err) {
            setError((err as Error).message)
        } finally {
            setSaving(false)
        }
    }

    return (
        <div className="flex h-full flex-col">
            <header className="flex items-center justify-between gap-2 border-b border-border bg-muted/10 px-3 py-2">
                <div className="min-w-0 flex-1">
                    {state.isNew ? (
                        <input
                            type="text"
                            placeholder="incidents/db-pool.md"
                            value={state.path}
                            onChange={(e) => patch({ path: e.currentTarget.value })}
                            className="h-7 w-full rounded border border-input bg-background px-2 font-mono text-xs"
                        />
                    ) : (
                        <code className="truncate text-[0.8125rem] font-mono">{state.path}</code>
                    )}
                </div>
                <button
                    type="button"
                    onClick={onCancel}
                    disabled={saving}
                    className="inline-flex h-6 cursor-pointer items-center rounded border border-border bg-card px-2 text-[0.6875rem] hover:bg-accent disabled:opacity-50"
                >
                    Cancel
                </button>
                <button
                    type="button"
                    onClick={() => void submit()}
                    disabled={saving}
                    className="inline-flex h-6 cursor-pointer items-center rounded bg-primary px-2 text-[0.6875rem] font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                    {saving ? 'Saving…' : state.isNew ? 'Create' : 'Save'}
                </button>
            </header>
            <div className="flex-1 space-y-3 overflow-auto p-3">
                <label className="block">
                    <span className="text-[0.625rem] uppercase tracking-wide text-muted-foreground">
                        Description ({state.description.length}/280)
                    </span>
                    <input
                        type="text"
                        value={state.description}
                        onChange={(e) => patch({ description: e.currentTarget.value })}
                        placeholder="One-line summary the agent reads in list/search results"
                        maxLength={280}
                        className="mt-1 w-full rounded border border-input bg-background px-2 py-1 text-xs"
                    />
                </label>
                <label className="block">
                    <span className="text-[0.625rem] uppercase tracking-wide text-muted-foreground">Tags</span>
                    <input
                        type="text"
                        value={state.tags.join(', ')}
                        onChange={(e) =>
                            patch({
                                tags: e.currentTarget.value
                                    .split(',')
                                    .map((t) => t.trim())
                                    .filter(Boolean),
                            })
                        }
                        placeholder="comma, separated, tags"
                        className="mt-1 w-full rounded border border-input bg-background px-2 py-1 font-mono text-xs"
                    />
                </label>
                <label className="block">
                    <span className="text-[0.625rem] uppercase tracking-wide text-muted-foreground">
                        Content (Markdown)
                    </span>
                    <textarea
                        value={state.content}
                        onChange={(e) => patch({ content: e.currentTarget.value })}
                        rows={20}
                        className="mt-1 w-full rounded border border-input bg-background px-2 py-2 font-mono text-xs"
                        placeholder="## Section&#10;&#10;Body markdown."
                    />
                </label>
                {error ? (
                    <div className="rounded border border-destructive-foreground bg-destructive/10 px-3 py-2 text-xs text-destructive-foreground">
                        {error}
                    </div>
                ) : null}
            </div>
        </div>
    )
}
