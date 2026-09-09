import type { ReactNode } from 'react'
import { Suspense, useState } from 'react'

import { Button } from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { DiffStats } from './DiffStats'
import { EditorSkeleton } from './EditorSkeleton'
import { getDiffStats } from './toolDiffContent'

const DiffEditor = lazyWithRetry(() => import('./EditDiffRenderer').then((m) => ({ default: m.DiffEditor })))

/** Collapsed body cap — roughly a dozen diff lines, per the permission-card evidence design. Must stay in sync with the `max-h-60` class below. */
const COLLAPSED_MAX_HEIGHT_PX = 240
/** Monaco's approximate diff line height, used to decide whether the cap would actually clip. */
const APPROX_LINE_HEIGHT_PX = 18
/**
 * The diff editor's own height bounds, mirrored from `MonacoDiffEditor` so the loading fallback reserves the height
 * the editor settles on. Importing them from that module would pull Monaco into this chunk and defeat the lazy load.
 */
const EDITOR_MIN_LINES = 5
const EDITOR_MAX_LINES = 30
const EDITOR_PADDING_PX = 18

export interface DiffEvidenceCardProps {
    /** Identity in the header bar — a field label ('Source code') or a file path node. */
    label: ReactNode
    /** Current content; null renders an all-additions diff (nothing existed before). */
    oldText: string | null
    /** Proposed content; empty renders an all-deletions diff. */
    newText: string
    /** Pseudo/real path driving the diff viewer's syntax highlighting. */
    path?: string
}

/**
 * The permission card's evidence block for a change payload: a bordered card whose header bar carries
 * the identity and the +/- line stats, and whose body is the shared diff viewer showing every line
 * (side-by-side when the container affords it, no collapsed unchanged regions). Bodies taller than the
 * cap start clipped behind a fade with a "Show all n lines" expander, so the card stays scannable
 * without hiding what changed.
 */
export function DiffEvidenceCard({ label, oldText, newText, path }: DiffEvidenceCardProps): JSX.Element {
    const [showAll, setShowAll] = useState(false)

    const { added, removed } = getDiffStats(oldText, newText)
    const lineCount = Math.max(oldText?.split('\n').length ?? 0, newText ? newText.split('\n').length : 0)
    const collapsible = lineCount * APPROX_LINE_HEIGHT_PX > COLLAPSED_MAX_HEIGHT_PX
    const collapsed = collapsible && !showAll
    const editorLines = Math.max(EDITOR_MIN_LINES, Math.min(EDITOR_MAX_LINES, lineCount))
    const editorHeightPx = editorLines * APPROX_LINE_HEIGHT_PX + EDITOR_PADDING_PX

    return (
        <div className="flex flex-col rounded border border-border-secondary overflow-hidden min-w-0">
            <div className="flex items-center gap-2 border-b border-border-secondary bg-surface-secondary px-2 py-1 text-xs min-w-0">
                <span className="font-mono font-medium truncate">{label}</span>
                <DiffStats added={added} removed={removed} />
            </div>
            <div className={cn('min-w-0', collapsed && 'relative max-h-60 overflow-hidden')}>
                <Suspense fallback={<EditorSkeleton height={editorHeightPx} lines={editorLines} />}>
                    <DiffEditor
                        diff={{ type: 'diff', oldText, newText }}
                        path={path}
                        sideBySide
                        hideUnchanged={false}
                    />
                </Suspense>
                {collapsed && (
                    <div className="absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-surface-primary to-transparent pointer-events-none" />
                )}
            </div>
            {collapsible && (
                <Button
                    variant="link-muted"
                    size="xs"
                    className="self-center my-0.5"
                    onClick={() => setShowAll(!showAll)}
                >
                    {showAll ? 'Show less' : `Show all ${lineCount} lines`}
                </Button>
            )}
        </div>
    )
}
