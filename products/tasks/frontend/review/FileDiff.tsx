import { Suspense, lazy, useMemo } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonTag, LemonTagType, Spinner } from '@posthog/lemon-ui'

import { Language, getLanguage } from 'lib/components/CodeSnippet/CodeSnippet'

import { DiffStatsChip } from '../conversation/DiffStatsChip'
import { getFileExtension, getFileName } from '../conversation/lib/path'
import { DiffRenderer } from '../conversation/primitives/CodePreview'
import type { ChangedFile, FileDiffText } from './deriveChangedFiles'

// Lazy so the Monaco chunk only loads once a diff is actually expanded
const MonacoDiffEditor = lazy(() => import('lib/components/MonacoDiffEditor'))

/** Above this combined size Monaco gets slow per file; use the lightweight renderer instead. */
const MONACO_MAX_CHARS = 50_000
/** Above this combined size the LCS differ would also struggle; show a placeholder. */
const DIFF_MAX_CHARS = 500_000

export interface FileDiffProps {
    file: ChangedFile
    collapsed: boolean
    onToggle: () => void
    /** Cumulative old/new text derived from tool calls; null when unavailable. */
    diff: FileDiffText | null
}

const STATUS_TAGS: Record<ChangedFile['status'], { label: string; type: LemonTagType }> = {
    added: { label: 'Added', type: 'success' },
    modified: { label: 'Modified', type: 'default' },
    deleted: { label: 'Deleted', type: 'danger' },
    renamed: { label: 'Renamed', type: 'highlight' },
}

function splitFilePath(path: string): { dirPath: string; fileName: string } {
    const fileName = getFileName(path)
    const dirPath = path.slice(0, path.length - fileName.length).replace(/\/$/, '')
    return { dirPath, fileName }
}

// Language enum values largely match Monaco language ids, with a few exceptions
function monacoLanguageForPath(path: string): string {
    const ext = getFileExtension(path)
    switch (ext) {
        case 'ts':
        case 'tsx':
            return 'typescript'
        case 'js':
        case 'jsx':
        case 'mjs':
        case 'cjs':
            return 'javascript'
        case 'py':
            return 'python'
        case 'rs':
            return 'rust'
        case 'css':
        case 'scss':
            return 'css'
        case 'md':
        case 'mdx':
            return 'markdown'
        case 'sh':
        case 'bash':
        case 'zsh':
            return 'shell'
        case 'yml':
        case 'yaml':
            return 'yaml'
        case 'html':
        case 'htm':
            return 'html'
        case 'go':
            return 'go'
        case 'rb':
            return 'ruby'
        case 'json':
            return 'json'
        case 'sql':
            return 'sql'
        default:
            return 'plaintext'
    }
}

function snippetLanguageForPath(path: string): Language {
    const ext = getFileExtension(path)
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
        case 'sh':
        case 'bash':
        case 'zsh':
            return Language.Bash
        case 'yml':
            return Language.YAML
        case 'htm':
            return Language.HTML
        default:
            return getLanguage(ext)
    }
}

export function FileDiff({ file, collapsed, onToggle, diff }: FileDiffProps): JSX.Element {
    const statusTag = STATUS_TAGS[file.status]
    const { dirPath, fileName } = splitFilePath(file.path)

    const fileNameColor =
        file.status === 'added' ? 'text-success' : file.status === 'deleted' ? 'text-danger line-through' : ''

    return (
        <div className="border rounded overflow-hidden bg-bg-light">
            <button
                type="button"
                onClick={onToggle}
                aria-expanded={!collapsed}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-left cursor-pointer hover:bg-surface-secondary"
            >
                {collapsed ? (
                    <IconChevronRight className="shrink-0 text-muted" />
                ) : (
                    <IconChevronDown className="shrink-0 text-muted" />
                )}
                <span className="min-w-0 flex-1 truncate font-mono text-xs" title={file.path}>
                    {file.originalPath && (
                        <>
                            <span className="text-muted">{file.originalPath}</span>
                            <span className="px-1 text-muted">→</span>
                        </>
                    )}
                    {dirPath && <span className="text-muted">{dirPath}/</span>}
                    <span className={`font-semibold ${fileNameColor}`}>{fileName}</span>
                </span>
                <LemonTag type={statusTag.type} size="small">
                    {statusTag.label}
                </LemonTag>
                <DiffStatsChip additions={file.linesAdded ?? 0} deletions={file.linesRemoved ?? 0} />
            </button>
            {!collapsed && <FileDiffBody file={file} diff={diff} />}
        </div>
    )
}

function FileDiffBody({ file, diff }: { file: ChangedFile; diff: FileDiffText | null }): JSX.Element {
    const oldText = diff?.oldText ?? null
    const newText = diff?.newText ?? null
    const totalChars = (oldText?.length ?? 0) + (newText?.length ?? 0)
    const hasTextDiff = diff !== null && (oldText !== null || newText !== null)

    if (!hasTextDiff && file.patch) {
        return <PatchView patch={file.patch} />
    }

    if (!hasTextDiff) {
        return <DiffPlaceholder message="Diff unavailable for this file" />
    }

    if (totalChars > DIFF_MAX_CHARS) {
        return (
            <DiffPlaceholder
                message={`File is too large to display (${totalChars.toLocaleString()} characters, max ${DIFF_MAX_CHARS.toLocaleString()})`}
            />
        )
    }

    if (totalChars > MONACO_MAX_CHARS) {
        return (
            <div className="overflow-auto border-t text-xs max-h-[600px]">
                <DiffRenderer
                    oldContent={oldText ?? ''}
                    content={newText ?? ''}
                    language={snippetLanguageForPath(file.path)}
                />
            </div>
        )
    }

    return (
        <div className="border-t">
            <Suspense
                fallback={
                    <div className="flex items-center justify-center py-6">
                        <Spinner />
                    </div>
                }
            >
                <MonacoDiffEditor
                    original={oldText ?? ''}
                    value={newText ?? ''}
                    modified={newText ?? ''}
                    language={monacoLanguageForPath(file.path)}
                    options={{
                        renderSideBySide: false,
                        renderOverviewRuler: false,
                        scrollBeyondLastLine: false,
                        minimap: { enabled: false },
                        hideUnchangedRegions: {
                            enabled: true,
                            contextLineCount: 3,
                            minimumLineCount: 3,
                            revealLineCount: 20,
                        },
                        diffAlgorithm: 'advanced',
                    }}
                />
            </Suspense>
        </div>
    )
}

function DiffPlaceholder({ message }: { message: string }): JSX.Element {
    return <div className="border-t px-3 py-4 text-center text-xs text-muted">{message}</div>
}

/** Minimal unified-patch renderer for run.output entries that only carry a git patch. */
function PatchView({ patch }: { patch: string }): JSX.Element {
    const lines = useMemo(() => patch.split('\n'), [patch])

    return (
        <div className="overflow-auto border-t font-mono text-xs max-h-[600px]">
            {lines.map((line, index) => {
                const background = line.startsWith('+')
                    ? 'bg-success-highlight'
                    : line.startsWith('-')
                      ? 'bg-danger-highlight'
                      : line.startsWith('@@')
                        ? 'bg-surface-secondary text-muted'
                        : ''
                return (
                    <div key={index} className={`whitespace-pre-wrap px-2 ${background}`}>
                        {line || ' '}
                    </div>
                )
            })}
        </div>
    )
}
