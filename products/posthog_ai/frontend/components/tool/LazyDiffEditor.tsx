import { Suspense } from 'react'

import { lazyWithRetry } from 'lib/utils/retryImport'

import type { DiffEditorProps } from './EditDiffRenderer'
import { EditorSkeleton } from './EditorSkeleton'

const DiffEditor = lazyWithRetry(() => import('./EditDiffRenderer').then((m) => ({ default: m.DiffEditor })))

/**
 * The diff editor's height bounds, mirrored from `MonacoDiffEditor` so the loading fallback reserves the height
 * the editor settles on. Importing them from that module would pull Monaco into this chunk and defeat the lazy load.
 */
const EDITOR_LINE_HEIGHT_PX = 18
const EDITOR_MIN_LINES = 5
const EDITOR_MAX_LINES = 30
const EDITOR_PADDING_PX = 18

/**
 * Loads the Monaco-backed diff editor on first render, behind a skeleton sized to the diff. The approval and
 * evidence cards render through this boundary so their chunk never bundles Monaco.
 */
export function LazyDiffEditor(props: DiffEditorProps): JSX.Element {
    const { oldText, newText } = props.diff
    const lineCount = Math.max(oldText?.split('\n').length ?? 0, newText?.split('\n').length ?? 0)
    const lines = Math.max(EDITOR_MIN_LINES, Math.min(EDITOR_MAX_LINES, lineCount))

    return (
        <Suspense
            fallback={<EditorSkeleton height={lines * EDITOR_LINE_HEIGHT_PX + EDITOR_PADDING_PX} lines={lines} />}
        >
            <DiffEditor {...props} />
        </Suspense>
    )
}
