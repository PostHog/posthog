/**
 * `<BundleTree />` — filesystem-style viewer for an agent's bundle.
 *
 * Left: collapsible tree of paths derived from the flat file list.
 * Right: content viewer for the selected file, language-aware:
 *
 *   .md   → rendered as soft-wrapped prose with monospace headings
 *   .ts   → monospace code block
 *   .json → uses `<JsonView />` (tree by default, raw-toggle available)
 *   other → monospace text
 *
 * Selection state is internal — first file in the bundle is selected
 * on mount. Parent doesn't need to track it.
 */

'use client'

import {
    ChevronDownIcon,
    ChevronRightIcon,
    FileIcon,
    FileJsonIcon,
    FileTextIcon,
    FolderIcon,
    FolderOpenIcon,
} from 'lucide-react'
import { useMemo, useState } from 'react'

import { JsonView } from '@posthog/agent-chat'
import type { BundleFile, BundleFileLanguage } from '@posthog/agent-chat/fixtures'

export interface BundleTreeProps {
    files: BundleFile[]
    /**
     * Currently-selected file path. Owned by the parent so it can
     * sync with URL state. When `null`/`undefined`, falls back to the
     * sensible default (`agent.md` if present, else the first file).
     */
    selectedPath?: string | null
    onSelectPath?: (path: string) => void
}

export function BundleTree({ files, selectedPath, onSelectPath }: BundleTreeProps): React.ReactElement {
    // Fallback for uncontrolled use: agent.md first if it exists.
    const defaultPath = files.some((f) => f.path === 'agent.md') ? 'agent.md' : (files[0]?.path ?? '')
    const [internalSelected, setInternalSelected] = useState<string>(defaultPath)
    const selected = selectedPath ?? internalSelected

    const handleSelect = (path: string): void => {
        setInternalSelected(path)
        onSelectPath?.(path)
    }

    const tree = useMemo(() => buildTree(files), [files])
    const selectedFile = files.find((f) => f.path === selected) ?? null

    if (files.length === 0) {
        return (
            <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                This revision has no bundle files yet.
            </div>
        )
    }

    return (
        <div className="grid grid-cols-[220px_minmax(0,1fr)] overflow-hidden rounded-md border border-border bg-background">
            <div className="overflow-y-auto border-r border-border bg-muted/20 py-1.5">
                <TreeView node={tree} selected={selected} onSelect={handleSelect} depth={0} />
            </div>
            <div className="min-w-0">{selectedFile ? <FileViewer file={selectedFile} /> : <EmptyViewer />}</div>
        </div>
    )
}

/* ── Tree model + builder ─────────────────────────────────────────── */

interface DirNode {
    kind: 'dir'
    name: string
    path: string
    children: TreeNode[]
}
interface FileNode {
    kind: 'file'
    name: string
    path: string
    language: BundleFileLanguage
}
type TreeNode = DirNode | FileNode

function buildTree(files: BundleFile[]): DirNode {
    const root: DirNode = { kind: 'dir', name: '', path: '', children: [] }
    for (const file of files) {
        const parts = file.path.split('/')
        let cursor: DirNode = root
        for (let i = 0; i < parts.length - 1; i++) {
            const dirName = parts[i]
            const dirPath = parts.slice(0, i + 1).join('/')
            let existing = cursor.children.find((c): c is DirNode => c.kind === 'dir' && c.name === dirName)
            if (!existing) {
                existing = { kind: 'dir', name: dirName, path: dirPath, children: [] }
                cursor.children.push(existing)
            }
            cursor = existing
        }
        cursor.children.push({
            kind: 'file',
            name: parts[parts.length - 1],
            path: file.path,
            language: file.language,
        })
    }
    sortTree(root)
    return root
}

function sortTree(dir: DirNode, depth = 0): void {
    dir.children.sort((a, b) => {
        // Root only: `agent.md` always wins — it's the system prompt and
        // the highest-importance file in any bundle.
        if (depth === 0 && a.kind === 'file' && a.name === 'agent.md') {
            return -1
        }
        if (depth === 0 && b.kind === 'file' && b.name === 'agent.md') {
            return 1
        }
        // Folders before files, then alphabetical.
        if (a.kind !== b.kind) {
            return a.kind === 'dir' ? -1 : 1
        }
        return a.name.localeCompare(b.name)
    })
    for (const c of dir.children) {
        if (c.kind === 'dir') {
            sortTree(c, depth + 1)
        }
    }
}

/* ── Tree view ────────────────────────────────────────────────────── */

interface TreeViewProps {
    node: DirNode
    selected: string
    onSelect: (path: string) => void
    depth: number
}

function TreeView({ node, selected, onSelect, depth }: TreeViewProps): React.ReactElement {
    return (
        <ul className="text-xs">
            {node.children.map((child) =>
                child.kind === 'dir' ? (
                    <DirRow key={child.path} dir={child} selected={selected} onSelect={onSelect} depth={depth} />
                ) : (
                    <FileRow
                        key={child.path}
                        file={child}
                        selected={selected === child.path}
                        onSelect={onSelect}
                        depth={depth}
                    />
                )
            )}
        </ul>
    )
}

function DirRow({
    dir,
    selected,
    onSelect,
    depth,
}: {
    dir: DirNode
    selected: string
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
                {open ? <ChevronDownIcon className="h-3 w-3" /> : <ChevronRightIcon className="h-3 w-3" />}
                {open ? <FolderOpenIcon className="h-3.5 w-3.5" /> : <FolderIcon className="h-3.5 w-3.5" />}
                <span>{dir.name}</span>
            </button>
            {open ? <TreeView node={dir} selected={selected} onSelect={onSelect} depth={depth + 1} /> : null}
        </li>
    )
}

function FileRow({
    file,
    selected,
    onSelect,
    depth,
}: {
    file: FileNode
    selected: boolean
    onSelect: (path: string) => void
    depth: number
}): React.ReactElement {
    return (
        <li>
            <button
                type="button"
                onClick={() => onSelect(file.path)}
                aria-current={selected ? 'true' : undefined}
                className={
                    selected
                        ? 'flex w-full cursor-pointer items-center gap-1 bg-accent px-2 py-1 text-left text-foreground'
                        : 'flex w-full cursor-pointer items-center gap-1 px-2 py-1 text-left text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground'
                }
                style={{ paddingLeft: `${8 + depth * 12 + 16}px` }}
            >
                <FileIconFor language={file.language} />
                <span className="truncate">{file.name}</span>
            </button>
        </li>
    )
}

function FileIconFor({ language }: { language: BundleFileLanguage }): React.ReactElement {
    const cls = 'h-3.5 w-3.5 shrink-0'
    if (language === 'json') {
        return <FileJsonIcon className={cls} />
    }
    if (language === 'markdown' || language === 'text') {
        return <FileTextIcon className={cls} />
    }
    return <FileIcon className={cls} />
}

/* ── Right pane: file viewer ─────────────────────────────────────── */

function FileViewer({ file }: { file: BundleFile }): React.ReactElement {
    return (
        <div className="flex h-full flex-col">
            <div className="flex items-center gap-2 border-b border-border bg-muted/10 px-3 py-1.5">
                <FileIconFor language={file.language} />
                <code className="text-[0.6875rem] text-muted-foreground">{file.path}</code>
                <span className="ml-auto text-[0.625rem] uppercase tracking-wide text-muted-foreground/70">
                    {file.language}
                </span>
            </div>
            <div className="overflow-auto p-3">
                <FileBody file={file} />
            </div>
        </div>
    )
}

function FileBody({ file }: { file: BundleFile }): React.ReactElement {
    if (file.language === 'json') {
        // The JSON content is stored as a string; parse it for the tree view.
        let parsed: unknown = null
        try {
            parsed = JSON.parse(file.content)
        } catch {
            parsed = file.content
        }
        return <JsonView value={parsed} expandToLevel={2} />
    }
    if (file.language === 'markdown') {
        return <MarkdownPreview text={file.content} />
    }
    // Default: code-style preformatted.
    return (
        <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-md border border-border/60 bg-background/60 p-3 text-[0.75rem] leading-relaxed">
            <code>{file.content}</code>
        </pre>
    )
}

/**
 * Lightweight markdown preview — headings, paragraphs, code fences, lists.
 * Not a full parser; just enough to look like prose instead of raw text.
 */
function MarkdownPreview({ text }: { text: string }): React.ReactElement {
    const blocks = useMemo(() => parseMarkdownBlocks(text), [text])
    return (
        <article className="prose max-w-none space-y-3 text-sm leading-relaxed text-foreground">
            {blocks.map((b, i) => (
                <MarkdownBlock key={i} block={b} />
            ))}
        </article>
    )
}

type MdBlock =
    | { kind: 'heading'; level: number; text: string }
    | { kind: 'paragraph'; text: string }
    | { kind: 'list'; items: string[] }
    | { kind: 'code'; lang: string; text: string }

function parseMarkdownBlocks(text: string): MdBlock[] {
    const lines = text.split('\n')
    const blocks: MdBlock[] = []
    let i = 0
    while (i < lines.length) {
        const line = lines[i]
        if (line.startsWith('```')) {
            const lang = line.slice(3).trim()
            const code: string[] = []
            i++
            while (i < lines.length && !lines[i].startsWith('```')) {
                code.push(lines[i])
                i++
            }
            blocks.push({ kind: 'code', lang, text: code.join('\n') })
            i++ // skip the closing ```
            continue
        }
        if (/^#{1,6}\s/.test(line)) {
            const level = line.match(/^#+/)![0].length
            blocks.push({ kind: 'heading', level, text: line.replace(/^#+\s/, '') })
            i++
            continue
        }
        if (/^[-*]\s/.test(line)) {
            const items: string[] = []
            while (i < lines.length && /^[-*]\s/.test(lines[i])) {
                items.push(lines[i].replace(/^[-*]\s/, ''))
                i++
            }
            blocks.push({ kind: 'list', items })
            continue
        }
        if (line.trim() === '') {
            i++
            continue
        }
        // Paragraph: collect until blank or block boundary.
        const para: string[] = [line]
        i++
        while (i < lines.length && lines[i].trim() !== '' && !/^(#{1,6}\s|```|[-*]\s)/.test(lines[i])) {
            para.push(lines[i])
            i++
        }
        blocks.push({ kind: 'paragraph', text: para.join(' ') })
    }
    return blocks
}

function MarkdownBlock({ block }: { block: MdBlock }): React.ReactElement {
    if (block.kind === 'heading') {
        const size =
            block.level === 1
                ? 'text-lg font-semibold'
                : block.level === 2
                  ? 'text-base font-semibold'
                  : 'text-sm font-semibold uppercase tracking-wide text-muted-foreground'
        return <div className={size}>{block.text}</div>
    }
    if (block.kind === 'paragraph') {
        return <p className="text-sm leading-relaxed">{renderInline(block.text)}</p>
    }
    if (block.kind === 'list') {
        return (
            <ul className="list-inside list-disc space-y-1 text-sm leading-relaxed">
                {block.items.map((item, i) => (
                    <li key={i}>{renderInline(item)}</li>
                ))}
            </ul>
        )
    }
    return (
        <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-md border border-border/60 bg-muted/30 p-3 text-[0.75rem] leading-relaxed">
            <code>{block.text}</code>
        </pre>
    )
}

/** Render inline `code` spans without parsing emphasis. */
function renderInline(text: string): React.ReactElement {
    const parts = text.split(/(`[^`]+`)/g)
    return (
        <>
            {parts.map((part, i) => {
                if (part.startsWith('`') && part.endsWith('`')) {
                    return (
                        <code
                            key={i}
                            className="rounded bg-muted/60 px-1 py-0.5 font-mono text-[0.8125rem] text-foreground"
                        >
                            {part.slice(1, -1)}
                        </code>
                    )
                }
                return <span key={i}>{part}</span>
            })}
        </>
    )
}

function EmptyViewer(): React.ReactElement {
    return (
        <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
            Pick a file to view.
        </div>
    )
}
