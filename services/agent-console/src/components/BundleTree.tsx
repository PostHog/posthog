/**
 * `<BundleTree />` — filesystem-style viewer for an agent's bundle.
 *
 * Wraps the shared `<FileExplorer>` with bundle-specific right-pane
 * content: language-aware rendering for the selected file (`.md` →
 * prose w/ emphasis & links, `.ts`/`.js` → regex-highlighted code,
 * `.json` → JSON tree, else preformatted text).
 *
 * Selection state is internal — first file in the bundle is selected
 * on mount. Parent doesn't need to track it.
 */

'use client'

import { FileIcon, FileJsonIcon, FileTextIcon } from 'lucide-react'
import { useMemo, useState } from 'react'

import { JsonView } from '@posthog/agent-chat'
import type { BundleFile, BundleFileLanguage } from '@posthog/agent-chat/fixtures'

import { EditWithAIButton } from './EditWithAIButton'
import { FileExplorer, type FileTreeNode } from './FileExplorer'

export interface BundleTreeProps {
    files: BundleFile[]
    /**
     * Currently-selected file path. Owned by the parent so it can
     * sync with URL state. When `null`/`undefined`, falls back to the
     * sensible default (`agent.md` if present, else the first file).
     */
    selectedPath?: string | null
    onSelectPath?: (path: string) => void
    /**
     * Slug of the agent this bundle belongs to. When provided the file
     * viewer header gets an "Edit with AI" pill that seeds the
     * concierge with a file-targeted prompt.
     */
    agentSlug?: string
}

export function BundleTree({ files, selectedPath, onSelectPath, agentSlug }: BundleTreeProps): React.ReactElement {
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

    return (
        <FileExplorer
            storageKey="file-explorer:bundle"
            tree={tree}
            selectedPath={selected}
            onSelectPath={handleSelect}
            emptyMessage="This revision has no bundle files yet."
        >
            {selectedFile ? <FileViewer file={selectedFile} agentSlug={agentSlug} /> : <EmptyViewer />}
        </FileExplorer>
    )
}

/* ── Tree model + builder ─────────────────────────────────────────── */

interface InternalNode {
    type: 'file' | 'folder'
    name: string
    path?: string
    language?: BundleFileLanguage
    children?: InternalNode[]
}

function buildTree(files: BundleFile[]): FileTreeNode {
    const root: InternalNode = { type: 'folder', name: '', children: [] }
    for (const file of files) {
        const parts = file.path.split('/')
        let cursor: InternalNode = root
        for (let i = 0; i < parts.length - 1; i++) {
            const dirName = parts[i]
            cursor.children ??= []
            let existing = cursor.children.find((c) => c.type === 'folder' && c.name === dirName)
            if (!existing) {
                existing = { type: 'folder', name: dirName, children: [] }
                cursor.children.push(existing)
            }
            cursor = existing
        }
        cursor.children ??= []
        cursor.children.push({
            type: 'file',
            name: parts[parts.length - 1],
            path: file.path,
            language: file.language,
        })
    }
    sortTree(root)
    return toFileTreeNode(root)
}

function sortTree(dir: InternalNode, depth = 0): void {
    if (!dir.children) {
        return
    }
    dir.children.sort((a, b) => {
        // Root only: `agent.md` always wins — it's the system prompt and
        // the highest-importance file in any bundle.
        if (depth === 0 && a.type === 'file' && a.name === 'agent.md') {
            return -1
        }
        if (depth === 0 && b.type === 'file' && b.name === 'agent.md') {
            return 1
        }
        // Folders before files, then alphabetical.
        if (a.type !== b.type) {
            return a.type === 'folder' ? -1 : 1
        }
        return a.name.localeCompare(b.name)
    })
    for (const c of dir.children) {
        if (c.type === 'folder') {
            sortTree(c, depth + 1)
        }
    }
}

function toFileTreeNode(n: InternalNode): FileTreeNode {
    return {
        type: n.type,
        name: n.name,
        path: n.path,
        icon: n.type === 'file' && n.language ? <FileIconFor language={n.language} /> : undefined,
        children: n.children?.map(toFileTreeNode),
    }
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

function FileViewer({ file, agentSlug }: { file: BundleFile; agentSlug?: string }): React.ReactElement {
    return (
        <div className="flex h-full flex-col">
            <div className="flex items-center gap-2 border-b border-border bg-muted/10 px-3 py-1.5">
                <FileIconFor language={file.language} />
                <code className="text-[0.6875rem] text-muted-foreground">{file.path}</code>
                <span className="text-[0.625rem] uppercase tracking-wide text-muted-foreground/70">
                    {file.language}
                </span>
                {agentSlug ? (
                    <div className="ml-auto">
                        <EditWithAIButton
                            prompt={`Help me edit \`${file.path}\` in \`${agentSlug}\`.`}
                            agentSlug={agentSlug}
                            label="Edit"
                            compact
                        />
                    </div>
                ) : null}
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-3">
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
    if (file.language === 'typescript') {
        return <CodeBlock code={file.content} lang="typescript" />
    }
    // Default: plain preformatted text.
    return (
        <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-md border border-border/60 bg-card/60 p-3 text-[0.75rem] leading-relaxed">
            <code>{file.content}</code>
        </pre>
    )
}

/* ── Code highlighter ─────────────────────────────────────────────── */

/**
 * Tiny regex tokenizer for TS/JS — keywords, strings, comments, numbers,
 * type-y identifiers. Not a real parser; just enough to make `source.ts`
 * and `compiled.js` readable instead of a beige wall.
 *
 * Tokens are matched in priority order so e.g. a `//` inside a string
 * doesn't become a comment.
 */
const KEYWORDS = new Set([
    'await',
    'async',
    'break',
    'case',
    'catch',
    'class',
    'const',
    'continue',
    'debugger',
    'default',
    'delete',
    'do',
    'else',
    'enum',
    'export',
    'extends',
    'finally',
    'for',
    'from',
    'function',
    'get',
    'if',
    'implements',
    'import',
    'in',
    'instanceof',
    'interface',
    'let',
    'new',
    'of',
    'package',
    'private',
    'protected',
    'public',
    'readonly',
    'return',
    'set',
    'static',
    'super',
    'switch',
    'this',
    'throw',
    'try',
    'type',
    'typeof',
    'var',
    'void',
    'while',
    'with',
    'yield',
    'as',
    'satisfies',
    'keyof',
    'infer',
    'declare',
    'abstract',
    'override',
    'namespace',
    'module',
])
const LITERALS = new Set(['true', 'false', 'null', 'undefined', 'NaN', 'Infinity'])

interface Tok {
    type: 'kw' | 'lit' | 'str' | 'num' | 'cmt' | 'fn' | 'type' | 'punct' | 'plain'
    text: string
}

function tokenizeCode(src: string): Tok[] {
    const out: Tok[] = []
    let i = 0
    const n = src.length
    while (i < n) {
        const ch = src[i]
        const rest = src.slice(i)

        // Line comment
        if (ch === '/' && src[i + 1] === '/') {
            const end = src.indexOf('\n', i)
            const stop = end === -1 ? n : end
            out.push({ type: 'cmt', text: src.slice(i, stop) })
            i = stop
            continue
        }
        // Block comment
        if (ch === '/' && src[i + 1] === '*') {
            const end = src.indexOf('*/', i + 2)
            const stop = end === -1 ? n : end + 2
            out.push({ type: 'cmt', text: src.slice(i, stop) })
            i = stop
            continue
        }
        // Strings: '...' "..." `...` (template literals collapsed, no interp parsing)
        if (ch === '"' || ch === "'" || ch === '`') {
            const quote = ch
            let j = i + 1
            while (j < n) {
                if (src[j] === '\\') {
                    j += 2
                    continue
                }
                if (src[j] === quote) {
                    j++
                    break
                }
                j++
            }
            out.push({ type: 'str', text: src.slice(i, j) })
            i = j
            continue
        }
        // Numbers
        const numMatch = /^(?:0x[\da-fA-F_]+|0b[01_]+|0o[0-7_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)n?/.exec(rest)
        if (numMatch && (i === 0 || !/[A-Za-z_$]/.test(src[i - 1]))) {
            out.push({ type: 'num', text: numMatch[0] })
            i += numMatch[0].length
            continue
        }
        // Identifiers / keywords
        const idMatch = /^[A-Za-z_$][A-Za-z0-9_$]*/.exec(rest)
        if (idMatch) {
            const word = idMatch[0]
            if (KEYWORDS.has(word)) {
                out.push({ type: 'kw', text: word })
            } else if (LITERALS.has(word)) {
                out.push({ type: 'lit', text: word })
            } else if (src[i + word.length] === '(') {
                out.push({ type: 'fn', text: word })
            } else if (/^[A-Z]/.test(word)) {
                // Heuristic: PascalCase → type/component reference
                out.push({ type: 'type', text: word })
            } else {
                out.push({ type: 'plain', text: word })
            }
            i += word.length
            continue
        }
        // Punctuation cluster
        const punctMatch = /^[{}()[\];,.<>?:!=+\-*/%&|^~@]+/.exec(rest)
        if (punctMatch) {
            out.push({ type: 'punct', text: punctMatch[0] })
            i += punctMatch[0].length
            continue
        }
        // Whitespace / fallthrough
        const wsMatch = /^\s+/.exec(rest)
        if (wsMatch) {
            out.push({ type: 'plain', text: wsMatch[0] })
            i += wsMatch[0].length
            continue
        }
        out.push({ type: 'plain', text: ch })
        i++
    }
    return out
}

const TOK_CLASS: Record<Tok['type'], string> = {
    kw: 'text-violet-500 dark:text-violet-300',
    lit: 'text-amber-600 dark:text-amber-300',
    str: 'text-emerald-600 dark:text-emerald-300',
    num: 'text-amber-600 dark:text-amber-300',
    cmt: 'text-muted-foreground/70 italic',
    fn: 'text-sky-600 dark:text-sky-300',
    type: 'text-teal-600 dark:text-teal-300',
    punct: 'text-foreground/70',
    plain: '',
}

function CodeBlock({ code, lang }: { code: string; lang?: string }): React.ReactElement {
    const tokens = useMemo(() => tokenizeCode(code), [code])
    const showLangLabel = lang && lang !== 'text'
    return (
        <div className="relative rounded-md border border-border/60 bg-card/60">
            {showLangLabel ? (
                <div className="absolute right-2 top-1.5 text-[0.625rem] uppercase tracking-wide text-muted-foreground/60">
                    {lang}
                </div>
            ) : null}
            <pre className="overflow-x-auto whitespace-pre-wrap break-words p-3 font-mono text-[0.75rem] leading-relaxed">
                <code>
                    {tokens.map((t, i) => (
                        <span key={i} className={TOK_CLASS[t.type]}>
                            {t.text}
                        </span>
                    ))}
                </code>
            </pre>
        </div>
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
    | { kind: 'ul'; items: string[] }
    | { kind: 'ol'; items: string[] }
    | { kind: 'quote'; text: string }
    | { kind: 'hr' }
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
        if (/^(?:---|\*\*\*|___)\s*$/.test(line)) {
            blocks.push({ kind: 'hr' })
            i++
            continue
        }
        if (/^>\s?/.test(line)) {
            const quote: string[] = []
            while (i < lines.length && /^>\s?/.test(lines[i])) {
                quote.push(lines[i].replace(/^>\s?/, ''))
                i++
            }
            blocks.push({ kind: 'quote', text: quote.join(' ') })
            continue
        }
        if (/^[-*]\s/.test(line)) {
            const items: string[] = []
            while (i < lines.length && /^[-*]\s/.test(lines[i])) {
                items.push(lines[i].replace(/^[-*]\s/, ''))
                i++
            }
            blocks.push({ kind: 'ul', items })
            continue
        }
        if (/^\d+\.\s/.test(line)) {
            const items: string[] = []
            while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
                items.push(lines[i].replace(/^\d+\.\s/, ''))
                i++
            }
            blocks.push({ kind: 'ol', items })
            continue
        }
        if (line.trim() === '') {
            i++
            continue
        }
        // Paragraph: collect until blank or block boundary.
        const para: string[] = [line]
        i++
        while (
            i < lines.length &&
            lines[i].trim() !== '' &&
            !/^(#{1,6}\s|```|[-*]\s|\d+\.\s|>\s?|(?:---|\*\*\*|___)\s*$)/.test(lines[i])
        ) {
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
        return <div className={size}>{renderInline(block.text)}</div>
    }
    if (block.kind === 'paragraph') {
        return <p className="text-sm leading-relaxed">{renderInline(block.text)}</p>
    }
    if (block.kind === 'ul') {
        return (
            <ul className="list-inside list-disc space-y-1 text-sm leading-relaxed marker:text-muted-foreground/60">
                {block.items.map((item, i) => (
                    <li key={i}>{renderInline(item)}</li>
                ))}
            </ul>
        )
    }
    if (block.kind === 'ol') {
        return (
            <ol className="list-inside list-decimal space-y-1 text-sm leading-relaxed marker:text-muted-foreground/60">
                {block.items.map((item, i) => (
                    <li key={i}>{renderInline(item)}</li>
                ))}
            </ol>
        )
    }
    if (block.kind === 'quote') {
        return (
            <blockquote className="border-l-2 border-border pl-3 text-sm italic leading-relaxed text-muted-foreground">
                {renderInline(block.text)}
            </blockquote>
        )
    }
    if (block.kind === 'hr') {
        return <hr className="border-border/60" />
    }
    return <CodeBlock code={block.text} lang={block.lang || undefined} />
}

/**
 * Inline renderer: code spans, bold, italic, links. Tokenized via a single
 * regex split so the order of operations is explicit and stable. Anything
 * that doesn't match a token falls through as plain text.
 */
const INLINE_RE = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^)]+\)|https?:\/\/[^\s)]+)/g

function renderInline(text: string): React.ReactElement {
    const parts = text.split(INLINE_RE)
    return (
        <>
            {parts.map((part, i) => {
                if (!part) {
                    return null
                }
                if (part.startsWith('`') && part.endsWith('`') && part.length >= 2) {
                    return (
                        <code
                            key={i}
                            className="rounded bg-muted/60 px-1 py-0.5 font-mono text-[0.8125rem] text-foreground"
                        >
                            {part.slice(1, -1)}
                        </code>
                    )
                }
                if ((part.startsWith('**') && part.endsWith('**')) || (part.startsWith('__') && part.endsWith('__'))) {
                    return (
                        <strong key={i} className="font-semibold">
                            {part.slice(2, -2)}
                        </strong>
                    )
                }
                if (
                    (part.startsWith('*') && part.endsWith('*') && part.length > 2) ||
                    (part.startsWith('_') && part.endsWith('_') && part.length > 2)
                ) {
                    return (
                        <em key={i} className="italic">
                            {part.slice(1, -1)}
                        </em>
                    )
                }
                const linkMatch = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part)
                if (linkMatch) {
                    return (
                        <a
                            key={i}
                            href={linkMatch[2]}
                            target="_blank"
                            rel="noreferrer"
                            className="text-primary underline-offset-2 hover:underline"
                        >
                            {linkMatch[1]}
                        </a>
                    )
                }
                if (/^https?:\/\//.test(part)) {
                    return (
                        <a
                            key={i}
                            href={part}
                            target="_blank"
                            rel="noreferrer"
                            className="text-primary underline-offset-2 hover:underline"
                        >
                            {part}
                        </a>
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
