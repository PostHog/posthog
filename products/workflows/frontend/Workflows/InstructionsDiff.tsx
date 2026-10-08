import { Suspense } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import type { MonacoDiffEditorProps } from 'lib/components/MonacoDiffEditor'
import { lazyWithRetry } from 'lib/utils/retryImport'

const MonacoDiffEditor = lazyWithRetry(() => import('lib/components/MonacoDiffEditor'))

const DIFF_OPTIONS: MonacoDiffEditorProps['options'] = {
    readOnly: true,
    renderSideBySide: false,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    lineNumbers: 'off',
    folding: false,
    hideUnchangedRegions: { enabled: true },
    // The editor sizes itself to the diff after first layout. Without this, Monaco keeps its first
    // measured height and cuts off the last lines.
    automaticLayout: true,
    scrollbar: { alwaysConsumeMouseWheel: false },
    // The prompt list counts any difference as a change, so the diff must show whitespace-only edits too.
    ignoreTrimWhitespace: false,
}

export function InstructionsDiff({ before, after }: { before: string; after: string }): JSX.Element {
    // Monaco's theme is global, so a wrong value recolors every editor on the page. Read the attribute the
    // page CSS follows, as CodeEditor does, because themeLogic can lag behind it.
    const isDarkMode = document.body.getAttribute('theme') === 'dark'

    return (
        <div className="overflow-hidden rounded border">
            {before ? (
                <Suspense fallback={<LemonSkeleton className="h-24 w-full" />}>
                    <MonacoDiffEditor
                        original={before}
                        value={after}
                        modified={after}
                        language="markdown"
                        theme={isDarkMode ? 'vs-dark' : 'vs'}
                        options={DIFF_OPTIONS}
                        loading={<LemonSkeleton className="h-24 w-full" />}
                    />
                </Suspense>
            ) : (
                // Monaco reads empty text as one blank line, so a diff against it would show
                // that line as removed. With nothing before, all of the text is added.
                <pre className="m-0 p-2 whitespace-pre-wrap break-words font-mono text-xs bg-fill-success-highlight">
                    {after}
                </pre>
            )}
        </div>
    )
}
