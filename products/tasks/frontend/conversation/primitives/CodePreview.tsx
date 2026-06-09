import { useMemo } from 'react'

import { CodeLine, getLanguage, Language } from 'lib/components/CodeSnippet/CodeSnippet'

import { compactHomePath, getFileExtension } from '../lib/path'

export interface CodePreviewProps {
    content: string
    filePath?: string
    showPath?: boolean
    oldContent?: string | null
    firstLineNumber?: number
    maxHeight?: string
    cacheKey?: string
}

/**
 * Read-only code/diff/image preview for tool-call content.
 *
 * Ported from the Electron app's `CodePreview`, but with the CodeMirror editor
 * and `@pierre/diffs` dependencies replaced by PostHog's `CodeSnippet`
 * primitives and a self-contained LCS-based diff renderer. The three modes are
 * unchanged: a unified diff when `oldContent` is provided, an image preview for
 * image data URIs, and a plain syntax-highlighted listing otherwise.
 */
export function CodePreview({
    content,
    filePath,
    showPath = false,
    oldContent,
    firstLineNumber = 1,
    maxHeight,
    cacheKey,
}: CodePreviewProps): JSX.Element {
    const isDiff = oldContent !== undefined && oldContent !== null
    const imageDataUrl = useMemo(() => (isDiff ? null : parseImageDataUrl(content)), [isDiff, content])

    if (isDiff) {
        return (
            <DiffPreview
                content={content}
                filePath={filePath}
                showPath={showPath}
                oldContent={oldContent}
                maxHeight={maxHeight}
                cacheKey={cacheKey}
            />
        )
    }

    if (imageDataUrl) {
        return (
            <ImageDataUrlPreview
                filePath={filePath}
                showPath={showPath}
                mimeType={imageDataUrl.mimeType}
                base64={imageDataUrl.base64}
                maxHeight={maxHeight}
            />
        )
    }

    return (
        <PlainCodePreview
            content={content}
            filePath={filePath}
            showPath={showPath}
            firstLineNumber={firstLineNumber}
            maxHeight={maxHeight}
        />
    )
}

// ---------------------------------------------------------------------------
// Shared chrome
// ---------------------------------------------------------------------------

function PreviewContainer({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="overflow-hidden border-t border-border">{children}</div>
}

function PreviewPath({ filePath }: { filePath: string }): JSX.Element {
    return (
        <div className="border-b border-border px-3 py-2" title={filePath}>
            <code className="truncate text-[13px] text-muted">{compactHomePath(filePath)}</code>
        </div>
    )
}

// ---------------------------------------------------------------------------
// Image preview
// ---------------------------------------------------------------------------

function ImageDataUrlPreview({
    filePath,
    showPath,
    mimeType,
    base64,
    maxHeight,
}: {
    filePath?: string
    showPath?: boolean
    mimeType: string
    base64: string
    maxHeight?: string
}): JSX.Element {
    return (
        <PreviewContainer>
            {showPath && filePath && <PreviewPath filePath={filePath} />}
            <div
                className="flex items-center justify-center bg-surface-secondary p-2"
                style={maxHeight ? { maxHeight, overflow: 'auto' } : undefined}
            >
                <img
                    src={`data:${mimeType};base64,${base64}`}
                    alt={filePath ?? 'Image preview'}
                    className="max-h-96 max-w-full object-contain"
                />
            </div>
        </PreviewContainer>
    )
}

// ---------------------------------------------------------------------------
// Plain code preview
// ---------------------------------------------------------------------------

function PlainCodePreview({
    content,
    filePath,
    showPath,
    firstLineNumber,
    maxHeight,
}: {
    content: string
    filePath?: string
    showPath?: boolean
    firstLineNumber: number
    maxHeight?: string
}): JSX.Element {
    const language = languageForPath(filePath)
    const lines = useMemo(() => content.split('\n'), [content])

    return (
        <PreviewContainer>
            {showPath && filePath && <PreviewPath filePath={filePath} />}
            <div className="overflow-auto text-[12px]" style={maxHeight ? { maxHeight } : { maxHeight: '750px' }}>
                {lines.map((line, index) => (
                    <CodeListingLine
                        key={index}
                        lineNumber={firstLineNumber + index}
                        text={line}
                        language={language}
                    />
                ))}
            </div>
        </PreviewContainer>
    )
}

function CodeListingLine({
    lineNumber,
    text,
    language,
}: {
    lineNumber: number
    text: string
    language: Language
}): JSX.Element {
    return (
        <div className="flex items-start">
            <span className="select-none px-2 text-right text-muted opacity-60" style={{ minWidth: '3rem' }}>
                {lineNumber}
            </span>
            <div className="min-w-0 flex-1">
                <CodeLine text={text} language={language} wrapLines={true} />
            </div>
        </div>
    )
}

// ---------------------------------------------------------------------------
// Diff preview — self-contained LCS line differ
// ---------------------------------------------------------------------------

export type DiffLineKind = 'added' | 'removed' | 'context'

export interface DiffLine {
    kind: DiffLineKind
    text: string
    /** Line number in the old file (removed/context lines), else null. */
    oldNumber: number | null
    /** Line number in the new file (added/context lines), else null. */
    newNumber: number | null
}

/**
 * Diff two blobs into added/removed/context lines using a longest-common-
 * subsequence backtrace. Self-contained — replaces the `diff` npm package and
 * `@pierre/diffs` used by the reference. Suitable for the modestly sized files
 * tool calls preview; not tuned for huge inputs.
 */
export function computeLineDiff(oldText: string, newText: string): DiffLine[] {
    const oldLines = oldText.length === 0 ? [] : oldText.split('\n')
    const newLines = newText.length === 0 ? [] : newText.split('\n')

    const n = oldLines.length
    const m = newLines.length

    // lcs[i][j] = length of LCS of oldLines[i:] and newLines[j:].
    const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
    for (let i = n - 1; i >= 0; i--) {
        for (let j = m - 1; j >= 0; j--) {
            lcs[i][j] = oldLines[i] === newLines[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
        }
    }

    const result: DiffLine[] = []
    let i = 0
    let j = 0
    let oldNumber = 1
    let newNumber = 1

    while (i < n && j < m) {
        if (oldLines[i] === newLines[j]) {
            result.push({ kind: 'context', text: oldLines[i], oldNumber: oldNumber++, newNumber: newNumber++ })
            i++
            j++
        } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
            result.push({ kind: 'removed', text: oldLines[i], oldNumber: oldNumber++, newNumber: null })
            i++
        } else {
            result.push({ kind: 'added', text: newLines[j], oldNumber: null, newNumber: newNumber++ })
            j++
        }
    }
    while (i < n) {
        result.push({ kind: 'removed', text: oldLines[i++], oldNumber: oldNumber++, newNumber: null })
    }
    while (j < m) {
        result.push({ kind: 'added', text: newLines[j++], oldNumber: null, newNumber: newNumber++ })
    }

    return result
}

/**
 * Renders a unified diff with Tailwind add/remove tokens. Each line is
 * syntax-highlighted via `CodeSnippet`'s per-line highlighter so the diff still
 * reads like code.
 */
export function DiffRenderer({
    oldContent,
    content,
    language,
}: {
    oldContent: string
    content: string
    language: Language
}): JSX.Element {
    const lines = useMemo(() => computeLineDiff(oldContent, content), [oldContent, content])

    return (
        <div>
            {lines.map((line, index) => (
                <DiffLineRow key={index} line={line} language={language} />
            ))}
        </div>
    )
}

function DiffLineRow({ line, language }: { line: DiffLine; language: Language }): JSX.Element {
    const background =
        line.kind === 'added' ? 'bg-success-highlight' : line.kind === 'removed' ? 'bg-danger-highlight' : ''
    const marker = line.kind === 'added' ? '+' : line.kind === 'removed' ? '-' : ' '
    const markerColor =
        line.kind === 'added' ? 'text-success' : line.kind === 'removed' ? 'text-danger' : 'text-muted'

    return (
        <div className={`flex items-start ${background}`}>
            <span className="select-none px-1 text-right text-muted opacity-60" style={{ minWidth: '2.5rem' }}>
                {line.oldNumber ?? ''}
            </span>
            <span className="select-none px-1 text-right text-muted opacity-60" style={{ minWidth: '2.5rem' }}>
                {line.newNumber ?? ''}
            </span>
            <span className={`select-none px-1 ${markerColor}`}>{marker}</span>
            <div className="min-w-0 flex-1">
                <CodeLine text={line.text} language={language} wrapLines={true} />
            </div>
        </div>
    )
}

function DiffPreview({
    content,
    filePath,
    showPath,
    oldContent,
    maxHeight,
}: {
    content: string
    filePath?: string
    showPath?: boolean
    oldContent: string
    maxHeight?: string
    cacheKey?: string
}): JSX.Element {
    const language = languageForPath(filePath)

    return (
        <PreviewContainer>
            {showPath && filePath && <PreviewPath filePath={filePath} />}
            <div className="overflow-auto text-[12px]" style={maxHeight ? { maxHeight } : { maxHeight: '750px' }}>
                <DiffRenderer oldContent={oldContent} content={content} language={language} />
            </div>
        </PreviewContainer>
    )
}

// ---------------------------------------------------------------------------
// Helpers (self-contained — no @posthog/shared)
// ---------------------------------------------------------------------------

/** Map a file path's extension to a `CodeSnippet` language for highlighting. */
function languageForPath(filePath?: string): Language {
    if (!filePath) {
        return Language.Text
    }
    const ext = getFileExtension(filePath)
    switch (ext) {
        case 'ts':
        case 'tsx':
            return Language.TypeScript
        case 'js':
        case 'jsx':
        case 'mjs':
        case 'cjs':
            return Language.JavaScript
        case 'py':
            return Language.Python
        case 'rb':
            return Language.Ruby
        case 'go':
            return Language.Go
        case 'java':
            return Language.Java
        case 'kt':
        case 'kts':
            return Language.Kotlin
        case 'cs':
            return Language.CSharp
        case 'php':
            return Language.PHP
        case 'swift':
            return Language.Swift
        case 'ex':
        case 'exs':
            return Language.Elixir
        case 'dart':
            return Language.Dart
        case 'sh':
        case 'bash':
        case 'zsh':
            return Language.Bash
        case 'json':
            return Language.JSON
        case 'yaml':
        case 'yml':
            return Language.YAML
        case 'html':
        case 'htm':
            return Language.HTML
        case 'xml':
            return Language.XML
        case 'sql':
            return Language.SQL
        case 'tf':
        case 'hcl':
            return Language.HCL
        case 'groovy':
            return Language.Groovy
        default:
            return getLanguage(ext)
    }
}

interface ParsedImageDataUrl {
    mimeType: string
    base64: string
}

// SVG is intentionally excluded — it can carry <script> tags that execute when
// rendered as an <img> from a data URL. heic/heif can't decode in an <img> tag.
const ALLOWED_IMAGE_MIME_TYPES: ReadonlySet<string> = new Set([
    'image/png',
    'image/jpeg',
    'image/gif',
    'image/webp',
    'image/bmp',
    'image/x-icon',
    'image/vnd.microsoft.icon',
    'image/tiff',
    'image/avif',
])

const DATA_URL_PATTERN = /^data:([a-zA-Z]+\/[a-zA-Z0-9.+-]+)(?:;[a-zA-Z0-9-]+=[^;,]+)*;base64,([A-Za-z0-9+/=\s]+)$/
const MAX_DATA_URL_LENGTH = 20 * 1024 * 1024
const MAX_IMAGE_BASE64_LENGTH = 15 * 1024 * 1024

/** Parse and validate an image data URI. Returns null for non-image input. */
function parseImageDataUrl(value: string): ParsedImageDataUrl | null {
    if (typeof value !== 'string' || value.length === 0) {
        return null
    }
    if (value.length > MAX_DATA_URL_LENGTH) {
        return null
    }
    if (!/^\s{0,1024}data:/.test(value)) {
        return null
    }

    const trimmed = value.trim()
    if (trimmed.length === 0) {
        return null
    }

    const match = DATA_URL_PATTERN.exec(trimmed)
    if (!match) {
        return null
    }

    const mimeType = match[1].toLowerCase()
    if (!ALLOWED_IMAGE_MIME_TYPES.has(mimeType)) {
        return null
    }

    const base64 = match[2].replace(/\s+/g, '')
    if (base64.length === 0 || base64.length > MAX_IMAGE_BASE64_LENGTH) {
        return null
    }

    return { mimeType, base64 }
}
