import { useValues } from 'kea'
import { Suspense } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import type { MonacoDiffEditorProps } from 'lib/components/MonacoDiffEditor'
import { themeLogic } from 'lib/logic/themeLogic'
import { lazyWithRetry } from 'lib/utils/retryImport'

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
}

export function AiTaskPromptDiffs({ changes }: { changes: AiTaskPromptChange[] }): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    return (
        <div className="flex flex-col gap-2" data-attr="workflow-publish-ai-task-prompt-diffs">
            <span className="font-semibold">Changed AI task instructions</span>
            {changes.map((change) => (
                <div key={change.actionId} className="flex flex-col gap-1">
                    <span className="text-xs text-secondary">{change.stepName}</span>
                    <div className="overflow-hidden rounded border">
                        <Suspense fallback={<LemonSkeleton className="h-24 w-full" />}>
                            <MonacoDiffEditor
                                original={change.livePrompt}
                                value={change.stagedPrompt}
                                modified={change.stagedPrompt}
                                language="markdown"
                                theme={isDarkModeOn ? 'vs-dark' : 'vs'}
                                options={DIFF_OPTIONS}
                            />
                        </Suspense>
                    </div>
                </div>
            ))}
        </div>
    )
}
