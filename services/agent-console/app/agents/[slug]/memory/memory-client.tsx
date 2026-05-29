'use client'

import { notFound, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useState } from 'react'

import { Markdown } from '@posthog/agent-chat'

import { useSessionTeamId } from '@/components/session-context'
import {
    ApiError,
    createMemoryFile,
    deleteMemoryFile,
    getAgent,
    getMemoryTree,
    readMemoryFile,
    searchMemoryApi,
    updateMemoryFile,
    type MemorySearchResult,
    type MemoryTreeNode,
} from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'

const NEW_FILE_PLACEHOLDER_PATH = '__new__'

type ViewMode = 'rendered' | 'raw'

interface DraftState {
    path: string
    description: string
    content: string
    tags: string[]
    isNew: boolean
}

export function MemoryClient({ slug }: { slug: string }): React.ReactElement {
    const router = useRouter()
    const searchParams = useSearchParams()
    const teamId = useSessionTeamId()!

    const activePath = searchParams?.get('path') ?? null
    const searchCue = searchParams?.get('q') ?? ''

    const agent = useResource(() => getAgent(teamId, slug), [teamId, slug])
    const tree = useResource(() => getMemoryTree(teamId, slug), [teamId, slug])

    const [draft, setDraft] = useState<DraftState | null>(null)
    const [saving, setSaving] = useState(false)
    const [saveError, setSaveError] = useState<string | null>(null)
    const [viewMode, setViewMode] = useState<ViewMode>('rendered')

    const setUrl = useCallback(
        (next: { path?: string | null; q?: string | null }) => {
            const params = new URLSearchParams(searchParams?.toString() ?? '')
            if ('path' in next) {
                if (next.path) {
                    params.set('path', next.path)
                } else {
                    params.delete('path')
                }
            }
            if ('q' in next) {
                if (next.q) {
                    params.set('q', next.q)
                } else {
                    params.delete('q')
                }
            }
            const qs = params.toString()
            router.replace(`/agents/${slug}/memory${qs ? `?${qs}` : ''}`)
        },
        [router, searchParams, slug]
    )

    if (agent.error instanceof ApiError && agent.error.status === 404) {
        notFound()
    }
    if (agent.error) {
        return (
            <div className="px-6 py-6 text-sm text-destructive-foreground">
                Failed to load agent: {agent.error.message}
            </div>
        )
    }

    const startEditing = (file: { path: string; description: string; content: string; tags: string[] }): void => {
        setDraft({
            path: file.path,
            description: file.description,
            content: file.content,
            tags: file.tags,
            isNew: false,
        })
        setSaveError(null)
    }

    const startNew = (): void => {
        setDraft({
            path: '',
            description: '',
            content: '',
            tags: [],
            isNew: true,
        })
        setSaveError(null)
        setUrl({ path: NEW_FILE_PLACEHOLDER_PATH })
    }

    const cancelDraft = (): void => {
        setDraft(null)
        setSaveError(null)
        if (activePath === NEW_FILE_PLACEHOLDER_PATH) {
            setUrl({ path: null })
        }
    }

    const save = async (): Promise<void> => {
        if (!draft) {
            return
        }
        if (!draft.description.trim()) {
            setSaveError('Description is required.')
            return
        }
        if (draft.description.length > 280) {
            setSaveError('Description must be ≤ 280 characters.')
            return
        }
        if (draft.isNew && !/^[a-z0-9][a-z0-9_/-]*\.md$/.test(draft.path)) {
            setSaveError("Path must be lowercase a-z 0-9 _ - / only and end in '.md'.")
            return
        }
        setSaving(true)
        setSaveError(null)
        try {
            const saved = draft.isNew
                ? await createMemoryFile(teamId, slug, {
                      path: draft.path,
                      description: draft.description,
                      content: draft.content,
                      tags: draft.tags,
                  })
                : await updateMemoryFile(teamId, slug, draft.path, {
                      description: draft.description,
                      content: draft.content,
                      tags: draft.tags,
                  })
            setDraft(null)
            tree.reload()
            setUrl({ path: saved.path })
        } catch (err) {
            const e = err as Error
            setSaveError(e.message)
        } finally {
            setSaving(false)
        }
    }

    const onDelete = async (path: string): Promise<void> => {
        if (!confirm(`Delete ${path}? This cannot be undone.`)) {
            return
        }
        try {
            await deleteMemoryFile(teamId, slug, path)
            tree.reload()
            if (activePath === path) {
                setUrl({ path: null })
            }
        } catch (err) {
            const e = err as Error
            alert(`Delete failed: ${e.message}`)
        }
    }

    return (
        <div className="flex h-full flex-col">
            <header className="border-b border-border px-6 py-4">
                <button
                    onClick={() => router.push(`/agents/${slug}`)}
                    className="text-sm text-muted-foreground hover:underline"
                >
                    ← Back to {agent.data?.slug ?? slug}
                </button>
                <h1 className="mt-2 text-xl font-semibold">Memory</h1>
                <p className="text-sm text-muted-foreground">
                    S3-backed file store the agent reads + writes through{' '}
                    <code className="rounded bg-muted px-1 py-0.5 text-xs">@posthog/memory-*</code> tools. Human writes
                    here are committed directly — they bypass any approval gate the agent itself would hit.
                </p>
            </header>

            <div className="grid flex-1 grid-cols-[320px_1fr] divide-x divide-border overflow-hidden">
                <TreePane
                    teamId={teamId}
                    slug={slug}
                    treeData={tree.data?.root ?? null}
                    treeLoading={tree.loading}
                    treeError={tree.error}
                    activePath={activePath}
                    onSelect={(p) => {
                        setDraft(null)
                        setUrl({ path: p })
                    }}
                    onNew={startNew}
                    searchCue={searchCue}
                    onSearch={(q) => setUrl({ q: q || null })}
                />
                <ReaderPane
                    teamId={teamId}
                    slug={slug}
                    activePath={activePath === NEW_FILE_PLACEHOLDER_PATH ? null : activePath}
                    draft={draft}
                    saveError={saveError}
                    saving={saving}
                    isCreating={draft?.isNew ?? false}
                    viewMode={viewMode}
                    onSetViewMode={setViewMode}
                    onEdit={startEditing}
                    onChangeDraft={(patch) => setDraft((d) => (d ? { ...d, ...patch } : d))}
                    onSave={save}
                    onCancel={cancelDraft}
                    onDelete={onDelete}
                />
            </div>
        </div>
    )
}

function TreePane({
    teamId,
    slug,
    treeData,
    treeLoading,
    treeError,
    activePath,
    onSelect,
    onNew,
    searchCue,
    onSearch,
}: {
    teamId: number
    slug: string
    treeData: MemoryTreeNode | null
    treeLoading: boolean
    treeError: Error | null
    activePath: string | null
    onSelect: (path: string) => void
    onNew: () => void
    searchCue: string
    onSearch: (q: string) => void
}): React.ReactElement {
    const trimmedCue = searchCue.trim()
    const search = useResource(
        () => (trimmedCue ? searchMemoryApi(teamId, slug, trimmedCue) : Promise.resolve(null)),
        [teamId, slug, trimmedCue]
    )

    return (
        <aside className="flex flex-col overflow-hidden">
            <div className="space-y-2 border-b border-border px-3 py-3">
                <input
                    type="search"
                    placeholder="Search memory…"
                    defaultValue={searchCue}
                    onChange={(e) => onSearch(e.currentTarget.value)}
                    className="w-full rounded border border-input bg-background px-2 py-1 text-sm"
                />
                <button
                    onClick={onNew}
                    className="w-full rounded border border-border bg-card px-2 py-1 text-sm hover:bg-muted"
                >
                    + New memory
                </button>
            </div>
            <div className="flex-1 overflow-auto px-2 py-2 text-sm">
                {trimmedCue ? (
                    <SearchResults results={search.data?.results ?? []} loading={search.loading} onSelect={onSelect} />
                ) : (
                    <Tree
                        node={treeData}
                        loading={treeLoading}
                        error={treeError}
                        active={activePath}
                        onSelect={onSelect}
                    />
                )}
            </div>
        </aside>
    )
}

function Tree({
    node,
    loading,
    error,
    active,
    onSelect,
}: {
    node: MemoryTreeNode | null
    loading: boolean
    error: Error | null
    active: string | null
    onSelect: (path: string) => void
}): React.ReactElement {
    if (loading) {
        return <div className="px-2 text-xs text-muted-foreground">Loading…</div>
    }
    if (error) {
        return <div className="px-2 text-xs text-destructive-foreground">{error.message}</div>
    }
    if (!node || !node.children || node.children.length === 0) {
        return <div className="px-2 text-xs text-muted-foreground">No memory yet. Use “New memory” above.</div>
    }
    return (
        <ul className="space-y-0.5">
            {node.children.map((c) => (
                <TreeNode key={c.name} node={c} depth={0} active={active} onSelect={onSelect} />
            ))}
        </ul>
    )
}

function TreeNode({
    node,
    depth,
    active,
    onSelect,
}: {
    node: MemoryTreeNode
    depth: number
    active: string | null
    onSelect: (path: string) => void
}): React.ReactElement {
    const [open, setOpen] = useState(true)
    if (node.type === 'folder') {
        return (
            <li>
                <button
                    onClick={() => setOpen((o) => !o)}
                    className="flex w-full items-center gap-1 rounded px-2 py-1 text-left hover:bg-muted"
                    style={{ paddingLeft: depth * 12 + 8 }}
                >
                    <span className="text-muted-foreground">{open ? '▾' : '▸'}</span>
                    <span className="text-muted-foreground">📁</span>
                    <span>{node.name}</span>
                </button>
                {open && node.children && (
                    <ul>
                        {node.children.map((c) => (
                            <TreeNode key={c.name} node={c} depth={depth + 1} active={active} onSelect={onSelect} />
                        ))}
                    </ul>
                )}
            </li>
        )
    }
    const isActive = active === node.path
    return (
        <li>
            <button
                onClick={() => node.path && onSelect(node.path)}
                className={`w-full rounded px-2 py-1 text-left hover:bg-muted ${
                    isActive ? 'bg-muted font-medium' : ''
                }`}
                style={{ paddingLeft: depth * 12 + 8 }}
            >
                <div className="truncate">{node.name}</div>
                {node.description && <div className="truncate text-xs text-muted-foreground">{node.description}</div>}
            </button>
        </li>
    )
}

function SearchResults({
    results,
    loading,
    onSelect,
}: {
    results: MemorySearchResult[]
    loading: boolean
    onSelect: (path: string) => void
}): React.ReactElement {
    if (loading) {
        return <div className="px-2 text-xs text-muted-foreground">Searching…</div>
    }
    if (results.length === 0) {
        return <div className="px-2 text-xs text-muted-foreground">No matches.</div>
    }
    return (
        <ul className="space-y-1">
            {results.map((r) => (
                <li key={r.path}>
                    <button
                        onClick={() => onSelect(r.path)}
                        className="w-full rounded px-2 py-1 text-left hover:bg-muted"
                    >
                        <div className="flex items-center justify-between gap-2">
                            <span className="truncate font-medium">{r.path}</span>
                            <span className="text-xs text-muted-foreground">{r.score.toFixed(2)}</span>
                        </div>
                        {r.description && <div className="truncate text-xs text-muted-foreground">{r.description}</div>}
                        {r.snippet && <div className="truncate text-xs italic text-muted-foreground">{r.snippet}</div>}
                    </button>
                </li>
            ))}
        </ul>
    )
}

function ReaderPane({
    teamId,
    slug,
    activePath,
    draft,
    saving,
    saveError,
    isCreating,
    viewMode,
    onSetViewMode,
    onEdit,
    onChangeDraft,
    onSave,
    onCancel,
    onDelete,
}: {
    teamId: number
    slug: string
    activePath: string | null
    draft: DraftState | null
    saving: boolean
    saveError: string | null
    isCreating: boolean
    viewMode: ViewMode
    onSetViewMode: (mode: ViewMode) => void
    onEdit: (file: { path: string; description: string; content: string; tags: string[] }) => void
    onChangeDraft: (patch: Partial<DraftState>) => void
    onSave: () => Promise<void>
    onCancel: () => void
    onDelete: (path: string) => Promise<void>
}): React.ReactElement {
    const file = useResource(
        () => (activePath && !draft ? readMemoryFile(teamId, slug, activePath) : Promise.resolve(null)),
        [teamId, slug, activePath, draft?.path]
    )

    // Editor mode for create or update
    if (draft) {
        return (
            <main className="flex flex-col overflow-hidden">
                <header className="flex items-center justify-between gap-2 border-b border-border px-6 py-3">
                    <div className="min-w-0 flex-1">
                        {isCreating ? (
                            <input
                                type="text"
                                placeholder="incidents/db-pool.md"
                                value={draft.path}
                                onChange={(e) => onChangeDraft({ path: e.currentTarget.value })}
                                className="w-full rounded border border-input bg-background px-2 py-1 font-mono text-sm"
                            />
                        ) : (
                            <div className="truncate font-mono text-sm">{draft.path}</div>
                        )}
                    </div>
                    <button
                        onClick={onCancel}
                        disabled={saving}
                        className="rounded px-3 py-1 text-sm hover:bg-muted disabled:opacity-50"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={() => onSave()}
                        disabled={saving}
                        className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground disabled:opacity-50"
                    >
                        {saving ? 'Saving…' : isCreating ? 'Create' : 'Save'}
                    </button>
                </header>
                <div className="flex-1 overflow-auto px-6 py-4 space-y-4">
                    <label className="block">
                        <span className="text-xs uppercase tracking-wide text-muted-foreground">
                            Description ({draft.description.length}/280)
                        </span>
                        <input
                            type="text"
                            value={draft.description}
                            onChange={(e) => onChangeDraft({ description: e.currentTarget.value })}
                            placeholder="One-line summary the agent reads in list/search results"
                            maxLength={280}
                            className="mt-1 w-full rounded border border-input bg-background px-2 py-1 text-sm"
                        />
                    </label>
                    <label className="block">
                        <span className="text-xs uppercase tracking-wide text-muted-foreground">Tags</span>
                        <input
                            type="text"
                            value={draft.tags.join(', ')}
                            onChange={(e) =>
                                onChangeDraft({
                                    tags: e.currentTarget.value
                                        .split(',')
                                        .map((t) => t.trim())
                                        .filter(Boolean),
                                })
                            }
                            placeholder="comma, separated, tags"
                            className="mt-1 w-full rounded border border-input bg-background px-2 py-1 font-mono text-sm"
                        />
                    </label>
                    <label className="block">
                        <span className="text-xs uppercase tracking-wide text-muted-foreground">
                            Content (Markdown)
                        </span>
                        <textarea
                            value={draft.content}
                            onChange={(e) => onChangeDraft({ content: e.currentTarget.value })}
                            rows={24}
                            className="mt-1 w-full rounded border border-input bg-background px-2 py-2 font-mono text-sm"
                            placeholder="## Section&#10;&#10;Body markdown."
                        />
                    </label>
                    {saveError && (
                        <div className="rounded border border-destructive-foreground bg-destructive/10 px-3 py-2 text-sm text-destructive-foreground">
                            {saveError}
                        </div>
                    )}
                </div>
            </main>
        )
    }

    // Read-only viewer
    if (!activePath) {
        return (
            <main className="flex items-center justify-center text-sm text-muted-foreground">
                Select a memory file on the left, or create a new one.
            </main>
        )
    }
    if (file.loading) {
        return <main className="px-6 py-6 text-sm text-muted-foreground">Loading…</main>
    }
    if (file.error) {
        return (
            <main className="px-6 py-6 text-sm text-destructive-foreground">Failed to load: {file.error.message}</main>
        )
    }
    if (!file.data) {
        return <main />
    }

    const f = file.data
    return (
        <main className="flex flex-col overflow-hidden">
            <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-3">
                <div className="min-w-0 flex-1">
                    <div className="truncate font-mono text-sm">{f.path}</div>
                    <div className="mt-1 text-sm">{f.description}</div>
                    {f.tags.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                            {f.tags.map((t) => (
                                <span key={t} className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                                    {t}
                                </span>
                            ))}
                        </div>
                    )}
                    <div className="mt-1 text-xs text-muted-foreground">
                        {f.created_at && <>Created {new Date(f.created_at).toLocaleString()} · </>}
                        {f.updated_at && <>Updated {new Date(f.updated_at).toLocaleString()}</>}
                    </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                    <div className="flex overflow-hidden rounded border border-border text-xs">
                        <button
                            onClick={() => onSetViewMode('rendered')}
                            className={`px-2 py-1 ${
                                viewMode === 'rendered' ? 'bg-muted font-medium' : 'hover:bg-muted'
                            }`}
                            aria-pressed={viewMode === 'rendered'}
                        >
                            Rendered
                        </button>
                        <button
                            onClick={() => onSetViewMode('raw')}
                            className={`border-l border-border px-2 py-1 ${
                                viewMode === 'raw' ? 'bg-muted font-medium' : 'hover:bg-muted'
                            }`}
                            aria-pressed={viewMode === 'raw'}
                        >
                            Raw
                        </button>
                    </div>
                    <button
                        onClick={() => onEdit(f)}
                        className="rounded border border-border px-3 py-1 text-sm hover:bg-muted"
                    >
                        Edit
                    </button>
                    <button
                        onClick={() => onDelete(f.path)}
                        className="rounded border border-destructive-foreground/40 px-3 py-1 text-sm text-destructive-foreground hover:bg-destructive/10"
                    >
                        Delete
                    </button>
                </div>
            </header>
            {viewMode === 'rendered' ? (
                <div className="flex-1 overflow-auto px-6 py-4">
                    <Markdown>{f.content}</Markdown>
                </div>
            ) : (
                <pre className="flex-1 overflow-auto whitespace-pre-wrap break-words px-6 py-4 font-mono text-sm leading-relaxed">
                    {f.content}
                </pre>
            )}
        </main>
    )
}
