/**
 * `<FileExplorer>` — generic two-pane file explorer.
 *
 * Left: collapsible folder tree (or a flat list of search results
 * when the consumer is in search mode), an optional search input,
 * and an optional top-right action slot (e.g. "+ New").
 *
 * Right: arbitrary `children`. The consumer renders whatever fits
 * the selected file — bundle viewer, memory markdown reader/editor,
 * etc.
 *
 * Selection is controlled — the parent owns `selectedPath` so URL
 * state and refetch behaviour stay outside this component. Use the
 * same wrapper for the bundle (read-only) and for memory (editable)
 * so the two surfaces feel identical to navigate.
 */

'use client'

import { ChevronDownIcon, ChevronRightIcon, FileIcon, FolderIcon, FolderOpenIcon, SearchIcon } from 'lucide-react'
import { useState } from 'react'

import { usePersistedWidth } from '@/lib/usePersistedWidth'

export interface FileTreeNode {
    type: 'file' | 'folder'
    name: string
    /** Set on files (and optionally on folders) — the click target for selection. */
    path?: string
    /** Optional one-line annotation rendered under the name (e.g. memory description). */
    description?: string
    /** Optional icon override for the file row. Default is a generic file icon. */
    icon?: React.ReactNode
    children?: FileTreeNode[]
}

export interface FileExplorerSearchResult {
    path: string
    /** Defaults to `path` when omitted. */
    name?: string
    description?: string
    /** Short matched-context excerpt. */
    snippet?: string
    /** BM25 score or similar — rendered if present. */
    score?: number
}

interface SearchConfig {
    query: string
    onChange: (query: string) => void
    /** Non-null = results mode (renders flat list). Null/undefined = tree mode. */
    results?: FileExplorerSearchResult[] | null
    placeholder?: string
    loading?: boolean
}

export interface FileExplorerProps {
    /** Root of the tree. `null` means "no data yet" — the explorer shows a loader. */
    tree: FileTreeNode | null
    selectedPath: string | null
    onSelectPath: (path: string) => void
    /** Optional search input + flat results override. */
    search?: SearchConfig
    /** Top-of-left-pane action (e.g. a "+ New" link / button). */
    topAction?: React.ReactNode
    /** Right-pane content. */
    children: React.ReactNode
    /** Empty-state copy when the tree has no files and search isn't active. */
    emptyMessage?: string
    /** Pre-tree async state. */
    loading?: boolean
    error?: Error | null
    /** Initial left column width in px (used until the persisted value loads). Default 240. */
    leftWidth?: number
    /**
     * Minimum + maximum drag bounds for the left pane, in px.
     * Defaults to a sensible 180–480 range.
     */
    leftMin?: number
    leftMax?: number
    /**
     * `localStorage` key for persisting the left-pane width. Required —
     * distinct per surface (e.g. `'file-explorer:bundle'`) so the bundle
     * tree and memory tree resize independently.
     */
    storageKey: string
    /**
     * Outer wrapper height. Defaults to viewport-minus-padding so the
     * explorer never exceeds the window, but is comfortably tall on
     * large monitors. Both panes scroll independently within this
     * bound. Override with `'h-full'` (or any Tailwind class string)
     * when the parent already owns the height budget.
     */
    height?: string
}

export function FileExplorer({
    tree,
    selectedPath,
    onSelectPath,
    search,
    topAction,
    children,
    emptyMessage = 'No files yet.',
    loading,
    error,
    leftWidth = 240,
    leftMin = 180,
    leftMax = 480,
    storageKey,
    height = 'h-[calc(100vh-6rem)]',
}: FileExplorerProps): React.ReactElement {
    const searching = !!search && search.query.trim().length > 0
    const { width, onResizeStart, isResizing } = usePersistedWidth({
        storageKey,
        defaultWidth: leftWidth,
        min: leftMin,
        max: leftMax,
    })

    return (
        <div
            className={`grid overflow-hidden rounded-md border border-border bg-card ${height}`}
            style={{ gridTemplateColumns: `${width}px 4px minmax(0, 1fr)` }}
        >
            <div className="flex flex-col bg-muted/20">
                {(search || topAction) && (
                    <div className="space-y-2 border-b border-border bg-muted/30 px-2 py-2">
                        {search ? (
                            <div className="relative">
                                <SearchIcon className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
                                <input
                                    type="search"
                                    value={search.query}
                                    onChange={(e) => search.onChange(e.currentTarget.value)}
                                    placeholder={search.placeholder ?? 'Search…'}
                                    className="h-7 w-full rounded border border-input bg-background pl-7 pr-2 text-xs"
                                />
                            </div>
                        ) : null}
                        {topAction ? <div>{topAction}</div> : null}
                    </div>
                )}
                <div className="flex-1 overflow-y-auto py-1.5">
                    {loading ? (
                        <div className="px-3 py-2 text-xs text-muted-foreground">Loading…</div>
                    ) : error ? (
                        <div className="px-3 py-2 text-xs text-destructive-foreground">{error.message}</div>
                    ) : searching ? (
                        <SearchResultsList
                            results={search!.results ?? []}
                            loading={search!.loading}
                            selectedPath={selectedPath}
                            onSelectPath={onSelectPath}
                        />
                    ) : tree && tree.children && tree.children.length > 0 ? (
                        <TreeView node={tree} selected={selectedPath} onSelect={onSelectPath} depth={0} />
                    ) : (
                        <div className="px-3 py-2 text-xs text-muted-foreground">{emptyMessage}</div>
                    )}
                </div>
            </div>
            <div
                role="separator"
                aria-orientation="vertical"
                tabIndex={-1}
                onMouseDown={onResizeStart}
                className={
                    'group/handle h-full cursor-col-resize bg-border/60 transition-colors hover:bg-foreground/30 ' +
                    (isResizing ? 'bg-foreground/40' : '')
                }
            />
            <div className="flex min-h-0 min-w-0 flex-col overflow-hidden">{children}</div>
        </div>
    )
}

function TreeView({
    node,
    selected,
    onSelect,
    depth,
}: {
    node: FileTreeNode
    selected: string | null
    onSelect: (path: string) => void
    depth: number
}): React.ReactElement {
    return (
        <ul className="text-xs">
            {(node.children ?? []).map((child) =>
                child.type === 'folder' ? (
                    <FolderRow
                        key={`d:${child.name}:${child.path ?? ''}`}
                        node={child}
                        selected={selected}
                        onSelect={onSelect}
                        depth={depth}
                    />
                ) : (
                    <FileRow
                        key={`f:${child.path}`}
                        node={child}
                        selected={!!child.path && selected === child.path}
                        onSelect={onSelect}
                        depth={depth}
                    />
                )
            )}
        </ul>
    )
}

function FolderRow({
    node,
    selected,
    onSelect,
    depth,
}: {
    node: FileTreeNode
    selected: string | null
    onSelect: (path: string) => void
    depth: number
}): React.ReactElement {
    const [open, setOpen] = useState(true)
    return (
        <li>
            <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                className="flex w-full cursor-pointer items-center gap-1 px-2 py-1 text-left text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
                style={{ paddingLeft: `${8 + depth * 12}px` }}
            >
                {open ? (
                    <ChevronDownIcon className="h-3 w-3 shrink-0" />
                ) : (
                    <ChevronRightIcon className="h-3 w-3 shrink-0" />
                )}
                {open ? (
                    <FolderOpenIcon className="h-3.5 w-3.5 shrink-0" />
                ) : (
                    <FolderIcon className="h-3.5 w-3.5 shrink-0" />
                )}
                <span className="truncate">{node.name}</span>
            </button>
            {open && node.children && node.children.length > 0 ? (
                <TreeView
                    node={{ type: 'folder', name: node.name, children: node.children }}
                    selected={selected}
                    onSelect={onSelect}
                    depth={depth + 1}
                />
            ) : null}
        </li>
    )
}

function FileRow({
    node,
    selected,
    onSelect,
    depth,
}: {
    node: FileTreeNode
    selected: boolean
    onSelect: (path: string) => void
    depth: number
}): React.ReactElement {
    if (!node.path) {
        return <></>
    }
    return (
        <li>
            <button
                type="button"
                onClick={() => onSelect(node.path!)}
                aria-current={selected ? 'true' : undefined}
                className={
                    (selected
                        ? 'bg-accent text-foreground'
                        : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground') +
                    ' flex w-full cursor-pointer items-start gap-1.5 px-2 py-1 text-left transition-colors'
                }
                style={{ paddingLeft: `${8 + depth * 12 + 16}px` }}
            >
                <span className="mt-px shrink-0">{node.icon ?? <FileIcon className="h-3.5 w-3.5 shrink-0" />}</span>
                <span className="min-w-0 flex-1">
                    <span className="truncate">{node.name}</span>
                    {node.description ? (
                        <span className="block truncate text-[0.6875rem] text-muted-foreground/70">
                            {node.description}
                        </span>
                    ) : null}
                </span>
            </button>
        </li>
    )
}

function SearchResultsList({
    results,
    loading,
    selectedPath,
    onSelectPath,
}: {
    results: FileExplorerSearchResult[]
    loading?: boolean
    selectedPath: string | null
    onSelectPath: (path: string) => void
}): React.ReactElement {
    if (loading) {
        return <div className="px-3 py-2 text-xs text-muted-foreground">Searching…</div>
    }
    if (results.length === 0) {
        return <div className="px-3 py-2 text-xs text-muted-foreground">No matches.</div>
    }
    return (
        <ul className="space-y-0.5 px-1">
            {results.map((r) => {
                const isActive = selectedPath === r.path
                return (
                    <li key={r.path}>
                        <button
                            type="button"
                            onClick={() => onSelectPath(r.path)}
                            aria-current={isActive ? 'true' : undefined}
                            className={
                                (isActive
                                    ? 'bg-accent text-foreground'
                                    : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground') +
                                ' flex w-full cursor-pointer flex-col gap-0.5 rounded px-2 py-1 text-left text-xs transition-colors'
                            }
                        >
                            <div className="flex items-center justify-between gap-2">
                                <span className="truncate font-medium">{r.name ?? r.path}</span>
                                {typeof r.score === 'number' ? (
                                    <span className="shrink-0 text-[0.625rem] text-muted-foreground/70">
                                        {r.score.toFixed(2)}
                                    </span>
                                ) : null}
                            </div>
                            {r.description ? (
                                <span className="truncate text-[0.6875rem] text-muted-foreground/80">
                                    {r.description}
                                </span>
                            ) : null}
                            {r.snippet ? (
                                <span className="truncate text-[0.6875rem] italic text-muted-foreground/70">
                                    {r.snippet}
                                </span>
                            ) : null}
                        </button>
                    </li>
                )
            })}
        </ul>
    )
}
