import type { FileOptions } from '@pierre/diffs'
import { File } from '@pierre/diffs/react'
import { useValues } from 'kea'
import { useMemo } from 'react'
import { useInView } from 'react-intersection-observer'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { EditorSkeleton } from './EditorSkeleton'

// Shiki bundled themes that read closest to GitHub's diff view; Pierre swaps between them based on
// `themeType`, which we drive off PostHog's own light/dark state.
const FILE_THEME = { light: 'github-light', dark: 'github-dark' } as const

export function ReadFileContent({ text, path }: { text: string; path?: string }): JSX.Element {
    // Lazy-mount: only parse/render once the card scrolls near the viewport.
    const { ref, inView } = useInView({ rootMargin: '500px', triggerOnce: true })
    const { isDarkModeOn } = useValues(themeLogic)

    const options = useMemo<FileOptions<undefined>>(
        () => ({
            theme: FILE_THEME,
            themeType: isDarkModeOn ? 'dark' : 'light',
            disableFileHeader: true,
            overflow: 'scroll',
        }),
        [isDarkModeOn]
    )

    return (
        <div ref={ref} className="w-full min-w-0">
            {inView ? (
                // Cap the height so a very large Read doesn't blow up the thread — scroll inside the card instead.
                <div className="max-h-[548px] overflow-y-auto rounded border border-border-secondary">
                    <File file={{ name: path ?? 'file', contents: text }} options={options} disableWorkerPool />
                </div>
            ) : (
                <EditorSkeleton />
            )}
        </div>
    )
}
