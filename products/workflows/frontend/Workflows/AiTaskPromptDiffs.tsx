import { Suspense } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import type { MonacoDiffEditorProps } from 'lib/components/MonacoDiffEditor'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

import type { AiTaskPromptChange } from './workflowLogic'

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

export function AiTaskPromptDiffs({ changes }: { changes: AiTaskPromptChange[] }): JSX.Element {
    // Monaco's theme is global, so a wrong value recolors every editor on the page. Read the attribute the
    // page CSS follows, as CodeEditor does, because themeLogic can lag behind it.
    const isDarkMode = document.body.getAttribute('theme') === 'dark'

    return (
        <div className="flex flex-col gap-2" data-attr="workflow-publish-ai-task-prompt-diffs">
            <span className="font-semibold">Changed AI task instructions</span>
            {/* The dialog renders in its own React root, outside the app's chunk-load recovery. Without this
                boundary, a failed editor load would unmount the whole dialog and its publish button. */}
            <ErrorBoundary>
                {changes.map((change) => (
                    <div key={change.actionId} className="flex flex-col gap-1">
                        <span className="text-xs text-secondary break-words">{change.stepName}</span>
                        <div className="overflow-hidden rounded border">
                            <Suspense fallback={<LemonSkeleton className="h-24 w-full" />}>
                                <MonacoDiffEditor
                                    original={change.livePrompt}
                                    value={change.stagedPrompt}
                                    modified={change.stagedPrompt}
                                    language="markdown"
                                    theme={isDarkMode ? 'vs-dark' : 'vs'}
                                    options={DIFF_OPTIONS}
                                    loading={<LemonSkeleton className="h-24 w-full" />}
                                />
                            </Suspense>
                        </div>
                    </div>
                ))}
            </ErrorBoundary>
        </div>
    )
}
