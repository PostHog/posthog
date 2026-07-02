import { type FileDiffMetadata, type FileDiffOptions, parseDiffFromFile } from '@pierre/diffs'
import { FileDiff } from '@pierre/diffs/react'
import { useValues } from 'kea'
import { useMemo } from 'react'
import { useInView } from 'react-intersection-observer'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { EditorSkeleton } from './EditorSkeleton'

// Shiki bundled themes that read closest to GitHub's diff view; Pierre swaps between them based on
// `themeType`, which we drive off PostHog's own light/dark state.
const DIFF_THEME = { light: 'github-light', dark: 'github-dark' } as const

/**
 * Read-only, GitHub-style rendering of an edit — parses the before/after file contents into a
 * `@pierre/diffs` diff and renders it unified, in a card that reads cleanly embedded in a chat card
 * (no editor chrome, our own file header rendered by the caller). Lazy-mounted: only parses/renders
 * once the card scrolls near the viewport.
 */
export function DiffFileContent({
    oldText,
    newText,
    path,
}: {
    oldText: string
    newText: string
    path?: string
}): JSX.Element {
    const { ref, inView } = useInView({ rootMargin: '500px', triggerOnce: true })
    const { isDarkModeOn } = useValues(themeLogic)

    const name = path ?? 'file'
    const [parseFailed, fileDiff] = useMemo<[boolean, FileDiffMetadata | null]>(() => {
        if (!inView) {
            return [false, null]
        }
        try {
            return [false, parseDiffFromFile({ name, contents: oldText }, { name, contents: newText })]
        } catch {
            return [true, null]
        }
    }, [inView, name, oldText, newText])

    const options = useMemo<FileDiffOptions<undefined>>(
        () => ({
            theme: DIFF_THEME,
            themeType: isDarkModeOn ? 'dark' : 'light',
            diffStyle: 'unified',
            disableFileHeader: true,
            overflow: 'scroll',
        }),
        [isDarkModeOn]
    )

    return (
        <div ref={ref} className="w-full min-w-0">
            {!inView ? (
                <EditorSkeleton />
            ) : parseFailed || !fileDiff ? (
                <pre className="m-0 whitespace-pre-wrap rounded border border-border-secondary p-2 text-xs">
                    {newText}
                </pre>
            ) : (
                <div className="rounded border border-border-secondary overflow-hidden">
                    <FileDiff fileDiff={fileDiff} options={options} disableWorkerPool />
                </div>
            )}
        </div>
    )
}
