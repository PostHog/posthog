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
import { useEffect, useMemo, useState } from 'react'

import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@posthog/quill'

export interface FileTreeNode {
    type: 'file' | 'folder'
    name: string
    /** Set on files (and optionally on folders) — the click target for selection. */
    path?: string
    /** Optional one-line annotation rendered under the name (e.g. memory description). */
    description?: string
    /** Optional icon override for the file row. Default is a generic file icon. */
    icon?: React.ReactNode
    /** Optional right-aligned slot (e.g. an approval lock or a "needs attention" badge). */
    trailing?: React.ReactNode
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
    /** Initial left column width in px (used the first time, before any persisted layout exists). */
    leftWidth?: number
    /**
     * Minimum + maximum drag bounds for the left pane, in px. Passed to
     * the underlying Quill `<ResizablePanel>` as `minSize` / `maxSize`.
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
     * Outer wrapper height as a raw CSS value (e.g. `'calc(100vh - 6rem)'`,
     * `'600px'`, `'100%'`). Defaults to viewport-minus-padding so the
     * explorer never exceeds the window. Passed as an inline `style`
     * because react-resizable-panels sets `height: 100%` inline on the
     * underlying group element, which would beat any `h-*` class.
     */
    height?: string
}

type Layout = Record<string, number>

const LEFT_PANEL_ID = 'left'
const RIGHT_PANEL_ID = 'right'

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
    height = 'calc(100vh - 6rem)',
}: FileExplorerProps): React.ReactElement {
    const searching = !!search && search.query.trim().length > 0

    // The Quill primitives are built on react-resizable-panels v4, which
    // wants `defaultLayout` at mount and emits `onLayoutChanged` afterwards.
    // We hydrate from localStorage on mount so SSR + first paint use the
    // fallback; the panel group then mounts with the real layout.
    const [layout, setLayout] = useState<Layout | null>(null)

    useEffect(() => {
        const fallback: Layout = { [LEFT_PANEL_ID]: leftWidth, [RIGHT_PANEL_ID]: 1000 }
        if (typeof window === 'undefined') {
            setLayout(fallback)
            return
        }
        try {
            const raw = window.localStorage.getItem(storageKey)
            if (raw) {
                const parsed = JSON.parse(raw) as unknown
                if (isLayout(parsed)) {
                    setLayout(parsed)
                    return
                }
            }
        } catch {
            // Corrupt entry / blocked storage — keep the fallback.
        }
        setLayout(fallback)
    }, [storageKey, leftWidth])

    if (!layout) {
        // One paint of an empty card while we read storage. Avoids the
        // alternative of mounting with the fallback then remounting with
        // the hydrated layout, which would flash.
        return <div className="rounded-md border border-border bg-card" style={{ height }} aria-hidden />
    }

    const onLayoutChanged = (next: Layout): void => {
        if (typeof window === 'undefined') {
            return
        }
        try {
            window.localStorage.setItem(storageKey, JSON.stringify(next))
        } catch {
            // Quota / disabled storage — layout stays in memory only.
        }
    }

    return (
        <ResizablePanelGroup
            orientation="horizontal"
            defaultLayout={layout}
            onLayoutChanged={onLayoutChanged}
            className="overflow-hidden rounded-md border border-border bg-card"
            style={{ height }}
        >
            <ResizablePanel id={LEFT_PANEL_ID} minSize={`${leftMin}px`} maxSize={`${leftMax}px`}>
                <div className="flex h-full flex-col bg-muted/20">
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
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel id={RIGHT_PANEL_ID}>
                <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">{children}</div>
            </ResizablePanel>
        </ResizablePanelGroup>
    )
}

function isLayout(value: unknown): value is Layout {
    if (!value || typeof value !== 'object') {
        return false
    }
    return Object.values(value as Record<string, unknown>).every((v) => typeof v === 'number' && Number.isFinite(v))
}

// Selected rows get a primary tint plus a left accent bar (drawn with an inset
// box-shadow so it costs no layout width and survives the inline left padding).
// Shared by folder rows, file rows, and search results so selection reads the
// same everywhere.
const ROW_SELECTED = 'bg-primary/10 font-medium text-foreground shadow-[inset_2px_0_0_0_var(--color-primary)]'
const ROW_IDLE = 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'

/** Whether `path` is the path of this node or any descendant — used to keep a
 *  folder open while its selected child is buried inside it. */
function subtreeContains(node: FileTreeNode, path: string | null): boolean {
    if (!path) {
        return false
    }
    for (const child of node.children ?? []) {
        if (child.path === path || subtreeContains(child, path)) {
            return true
        }
    }
    return false
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
    // Folders are selectable when they carry a `path` (e.g. a config section
    // whose detail is a section overview). Clicking always toggles open; if it
    // has a path it also selects, so the selection stays put across toggles.
    const isSelected = !!node.path && selected === node.path
    // Auto-open when the selection lands on a buried child (e.g. a jump from the
    // detail pane) so the active item is always revealed. Manual collapse still
    // works afterward — this only fires when the selection enters the subtree.
    const hasSelectedChild = useMemo(() => subtreeContains(node, selected), [node, selected])
    useEffect(() => {
        if (hasSelectedChild) {
            setOpen(true)
        }
    }, [hasSelectedChild])
    return (
        <li>
            <button
                type="button"
                onClick={() => {
                    setOpen((o) => !o)
                    if (node.path) {
                        onSelect(node.path)
                    }
                }}
                aria-current={isSelected ? 'true' : undefined}
                className={
                    (isSelected ? ROW_SELECTED : ROW_IDLE) +
                    ' flex w-full cursor-pointer items-center gap-1 px-2 py-1 text-left transition-colors'
                }
                style={{ paddingLeft: `${8 + depth * 12}px` }}
            >
                {open ? (
                    <ChevronDownIcon className="h-3 w-3 shrink-0" />
                ) : (
                    <ChevronRightIcon className="h-3 w-3 shrink-0" />
                )}
                {node.icon ??
                    (open ? (
                        <FolderOpenIcon className="h-3.5 w-3.5 shrink-0" />
                    ) : (
                        <FolderIcon className="h-3.5 w-3.5 shrink-0" />
                    ))}
                <span className="min-w-0 flex-1 truncate">{node.name}</span>
                {node.trailing ? <span className="ml-auto shrink-0 pl-1">{node.trailing}</span> : null}
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
                    (selected ? ROW_SELECTED : ROW_IDLE) +
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
                {node.trailing ? <span className="mt-px shrink-0 pl-1">{node.trailing}</span> : null}
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
                                (isActive ? ROW_SELECTED : ROW_IDLE) +
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
