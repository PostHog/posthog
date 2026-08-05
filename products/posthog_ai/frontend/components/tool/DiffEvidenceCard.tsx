import type { ReactNode } from 'react'
import { useState } from 'react'

import { Button } from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'

import { DiffEditor, DiffStats } from './EditDiffRenderer'
import { getDiffStats } from './toolDiffContent'

/** Collapsed body cap — roughly a dozen diff lines, per the permission-card evidence design. Must stay in sync with the `max-h-60` class below. */
const COLLAPSED_MAX_HEIGHT_PX = 240
/** Monaco's approximate diff line height, used to decide whether the cap would actually clip. */
const APPROX_LINE_HEIGHT_PX = 18

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

    return (
        <div className="flex flex-col rounded border border-border-secondary overflow-hidden min-w-0">
            <div className="flex items-center gap-2 border-b border-border-secondary bg-surface-secondary px-2 py-1 text-xs min-w-0">
                <span className="font-mono font-medium truncate">{label}</span>
                <DiffStats added={added} removed={removed} />
            </div>
            <div className={cn('min-w-0', collapsed && 'relative max-h-60 overflow-hidden')}>
                <DiffEditor diff={{ type: 'diff', oldText, newText }} path={path} sideBySide hideUnchanged={false} />
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
