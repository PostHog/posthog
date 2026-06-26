import Editor from '@monaco-editor/react'
import { useValues } from 'kea'
import type { editor } from 'monaco-editor'
import { useInView } from 'react-intersection-observer'

import 'lib/monaco/monacoEnvironment'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { EditorSkeleton } from './EditorSkeleton'
import { languageFromPath } from './toolDiffContent'

const LINE_HEIGHT = 18
const MIN_LINES = 5
const MAX_LINES = 30

// Read-only single-pane file view: a plain editor (not a diff editor), so there's one line-number gutter.
// Module-level so the object identity is stable across renders — monaco calls `updateOptions` whenever
// this prop changes.
const READ_EDITOR_OPTIONS: editor.IStandaloneEditorConstructionOptions = {
    readOnly: true,
    wordWrap: 'on',
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
    guides: { indentation: false },
    padding: { top: 4, bottom: 4 },
    automaticLayout: true,
    renderGutterMenu: false,
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

    return (
        <div ref={ref} className="w-full min-w-0">
            {inView ? (
                <Editor
                    value={text}
                    language={languageFromPath(path)}
                    theme={isDarkModeOn ? 'vs-dark' : 'vs'}
                    options={READ_EDITOR_OPTIONS}
                    height={height}
                    loading={<EditorSkeleton height={height} />}
                />
            ) : (
                <div className="h-24 rounded border border-border-secondary" />
            )}
        </div>
    )
}
