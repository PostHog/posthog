import { useValues } from 'kea'
import type { editor } from 'monaco-editor'
import { useInView } from 'react-intersection-observer'

import { IconPencil } from '@posthog/icons'

import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { EditorSkeleton } from './EditorSkeleton'
import { FilePath } from './FilePath'
import { GenericMcpToolRenderer } from './GenericMcpToolRenderer'
import { ReadFileContent } from './ReadFileContent'
import { ToolActivity } from './ToolActivity'
import { findAllDiffContent, getDiffStats, languageFromPath, type ToolCallDiffContent } from './toolDiffContent'
import type { ToolRendererProps } from './toolRegistry'

// A stripped-down, unified diff that reads cleanly embedded in a chat card — mirrors the look of the
// sandbox agent's own diff UI (unified style, soft-wrapped, compact font, no editor chrome). Module-level
// so the object identity is stable across renders: MonacoDiffEditor calls `updateOptions` whenever this
// prop changes, and a fresh literal each render would thrash it during streaming.
const DIFF_EDITOR_OPTIONS: editor.IDiffEditorConstructionOptions = {
    readOnly: true,
    renderSideBySide: false,
    hideUnchangedRegions: { enabled: true },
    diffAlgorithm: 'advanced',
    wordWrap: 'on',
    diffWordWrap: 'inherit',
    fontSize: 12,
    lineNumbers: 'on',
    minimap: { enabled: false },
    renderOverviewRuler: false,
    overviewRulerLanes: 0,
    overviewRulerBorder: false,
    hideCursorInOverviewRuler: true,
    scrollBeyondLastLine: false,
    folding: false,
    glyphMargin: false,
    renderLineHighlight: 'none',
    renderGutterMenu: false,
    guides: { indentation: false },
    padding: { top: 4, bottom: 4 },
    // Don't trap the thread's scroll when the cursor is over the diff.
    scrollbar: { alwaysConsumeMouseWheel: false, vertical: 'auto', horizontal: 'auto' },
}

function DiffEditor({ diff, path }: { diff: ToolCallDiffContent; path?: string }): JSX.Element {
    // Lazy-mount: only instantiate the Monaco diff editor once the card scrolls near the viewport.
    const { ref, inView } = useInView({ rootMargin: '500px', triggerOnce: true })
    // Match the surrounding app theme — without this Monaco falls back to its default `vs` (white) theme.
    const { isDarkModeOn } = useValues(themeLogic)

    return (
        <div ref={ref} className="w-full min-w-0">
            {inView ? (
                <MonacoDiffEditor
                    original={diff.oldText ?? ''}
                    value={diff.newText ?? ''}
                    modified={diff.newText ?? ''}
                    language={languageFromPath(path)}
                    theme={isDarkModeOn ? 'vs-dark' : 'vs'}
                    options={DIFF_EDITOR_OPTIONS}
                    loading={<EditorSkeleton />}
                />
            ) : (
                <div className="h-24 rounded border border-border-secondary" />
            )}
        </div>
    )
}

/** +added / -removed mono stat chip for a diff. */
function DiffStats({ added, removed }: { added: number; removed: number }): JSX.Element {
    return (
        <span className="font-mono text-xs shrink-0">
            <span className="text-success">+{added}</span> <span className="text-danger">-{removed}</span>
        </span>
    )
}

/**
 * Renderer for Edit / Write / MultiEdit / NotebookEdit. The header reads "Edited a file" / "Created a
 * file" (or "Edited N files"); expanding the card reveals the filename, line stats, and a per-file view:
 * a single-pane read-only editor for a newly created file (no "before" to diff against), an inline visual
 * diff for a real edit. Without `type: "diff"` content blocks it degrades to the generic card.
 */
export function EditDiffRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const diffs = findAllDiffContent(message.content)

    if (diffs.length === 0) {
        return <GenericMcpToolRenderer {...props} />
    }

    const fallbackPath = typeof message.rawInput.file_path === 'string' ? message.rawInput.file_path : undefined
    const isCreate = diffs.length === 1 && diffs[0].oldText == null
    const title = diffs.length > 1 ? `Edited ${diffs.length} files` : isCreate ? 'Created a file' : 'Edited a file'

    const body = (
        <div className="flex flex-col gap-3 w-full min-w-0">
            {diffs.map((diff, index) => {
                const path = diff.path ?? fallbackPath
                const stats = getDiffStats(diff.oldText, diff.newText)
                return (
                    <div key={index} className="flex flex-col gap-1 w-full min-w-0">
                        <div className="flex items-center gap-2 min-w-0">
                            {path && <FilePath path={path} />}
                            <DiffStats added={stats.added} removed={stats.removed} />
                        </div>
                        {diff.oldText == null ? (
                            <ReadFileContent text={diff.newText ?? ''} path={path} />
                        ) : (
                            <DiffEditor diff={diff} path={path} />
                        )}
                    </div>
                )
            })}
        </div>
    )

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconPencil />}
            title={title}
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
}
