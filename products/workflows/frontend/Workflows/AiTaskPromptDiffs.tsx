import { ErrorBoundary } from '~/layout/ErrorBoundary'

import { InstructionsDiff } from './InstructionsDiff'
import type { AiTaskPromptChange } from './workflowLogic'

export function AiTaskPromptDiffs({ changes }: { changes: AiTaskPromptChange[] }): JSX.Element {
    return (
        <div className="ph-no-capture flex flex-col gap-2" data-attr="workflow-publish-ai-task-prompt-diffs">
            <div className="flex flex-col">
                <span className="font-semibold">Changed AI task instructions</span>
                <span className="text-xs text-secondary">
                    Removed lines are what runs now. Added lines go live when you publish.
                </span>
            </div>
            {/* The dialog renders in its own React root, outside the app's chunk-load recovery. Without this
                boundary, a failed editor load would unmount the whole dialog and its publish button. */}
            <ErrorBoundary>
                {changes.map((change) => (
                    <div key={change.actionId} className="flex flex-col gap-1">
                        <span className="text-xs text-secondary break-words">{change.stepName}</span>
                        <InstructionsDiff before={change.livePrompt} after={change.stagedPrompt} />
                    </div>
                ))}
            </ErrorBoundary>
        </div>
    )
}
