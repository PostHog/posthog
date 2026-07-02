import { useValues } from 'kea'
import type { editor } from 'monaco-editor'
import { useEffect, useRef } from 'react'
import { useInView } from 'react-intersection-observer'

import 'lib/monaco/monacoEnvironment'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { EditorSkeleton } from './EditorSkeleton'
import { languageFromPath } from './toolDiffContent'

const LINE_HEIGHT = 18
const MIN_LINES = 5
const MAX_LINES = 30

// Module-level so the object identity is stable across renders — monaco calls `updateOptions` whenever
// this prop changes.
const READ_EDITOR_OPTIONS: editor.IStandaloneEditorConstructionOptions = {
    readOnly: true,
    wordWrap: 'on',
    fontSize: 12,
    lineNumbers: 'on',
    minimap: { enabled: false },
    overviewRulerLanes: 0,
    overviewRulerBorder: false,
    hideCursorInOverviewRuler: true,
    scrollBeyondLastLine: false,
    folding: false,
    glyphMargin: false,
    renderLineHighlight: 'none',
    guides: { indentation: false },
    padding: { top: 4, bottom: 4 },
    automaticLayout: true,
    // Don't trap the thread's scroll when the cursor is over the editor.
    scrollbar: { alwaysConsumeMouseWheel: false, vertical: 'auto', horizontal: 'auto' },
}

export function ReadFileContent({ text, path }: { text: string; path?: string }): JSX.Element {
    // Lazy-mount: only instantiate the Monaco editor once the card scrolls near the viewport.
    const { ref, inView } = useInView({ rootMargin: '500px', triggerOnce: true })
    // Match the surrounding app theme — without this Monaco falls back to its default `vs` (white) theme.
    const { isDarkModeOn } = useValues(themeLogic)
    const lineCount = Math.max(MIN_LINES, Math.min(MAX_LINES, text.split('\n').length))
    const height = lineCount * LINE_HEIGHT + 8

    const containerRef = useRef<HTMLDivElement>(null)
    const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null)

    useEffect(() => {
        if (!inView || !containerRef.current) {
            return
        }

        const container = containerRef.current
        let disposed = false

        // eslint-disable-next-line @typescript-eslint/no-floating-promises
        import('monaco-editor').then((monaco) => {
            if (disposed || !container) {
                return
            }
            const instance = monaco.editor.create(container, {
                value: text,
                language: languageFromPath(path),
                theme: isDarkModeOn ? 'vs-dark' : 'vs',
                ...READ_EDITOR_OPTIONS,
            })
            editorRef.current = instance
        })

        return () => {
            disposed = true
            editorRef.current?.dispose()
            editorRef.current = null
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [inView])

    useEffect(() => {
        const model = editorRef.current?.getModel()
        if (model) {
            model.setValue(text)
        }
    }, [text])

    useEffect(() => {
        editorRef.current?.updateOptions({ theme: isDarkModeOn ? 'vs-dark' : 'vs' })
    }, [isDarkModeOn])

    return (
        <div ref={ref} className="w-full min-w-0">
            {inView ? (
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ height }}
                    ref={containerRef}
                    className="w-full"
                />
            ) : (
                <EditorSkeleton height={height} />
            )}
        </div>
    )
}
