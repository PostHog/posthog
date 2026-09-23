import { IconSparkles } from '@posthog/icons'

import type { WizardRunApi, WizardRunTaskApi } from '../generated/api.schemas'
import { wizardRunCurrentState } from '../wizardRunDisplay'

export function WizardRunSyncCard({
    run,
    tasks,
    activeCount,
    onOpen,
}: {
    run: WizardRunApi
    tasks: readonly WizardRunTaskApi[]
    activeCount: number
    onOpen: () => void
}): JSX.Element {
    const currentTask = tasks.find((task) => task.status === 'running')

    return (
        <div
            className="fixed bottom-5 right-5 z-[60] w-[340px] max-w-[calc(100vw-2.5rem)] overflow-hidden rounded-xl border border-primary bg-surface-primary shadow-xl shadow-black/10"
            role="status"
            aria-live="polite"
            data-attr="wizard-run-sync-card"
        >
            <button
                type="button"
                className="flex w-full items-start gap-2.5 px-3.5 py-3 text-left hover:bg-fill-highlight-50"
                onClick={onOpen}
                aria-label={`Open details for ${run.program.name}`}
            >
                <IconSparkles className="mt-0.5 shrink-0 text-ai" />
                <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">
                        {currentTask?.name ?? wizardRunCurrentState(run)}
                    </span>
                    <span className="block truncate text-xs text-muted">{wizardRunCurrentState(run)}</span>
                    <span className="block truncate text-xs text-muted ph-no-capture">
                        {run.environment === 'cloud' ? 'Cloud' : 'Local'} ·{' '}
                        {run.workspace.type === 'git_repository'
                            ? run.workspace.repository
                            : run.workspace.project_name}
                    </span>
                </span>
            </button>
            {run.status === 'running' && tasks.length > 0 && (
                <ul className="max-h-40 space-y-1 overflow-y-auto border-t border-primary px-3.5 py-2 text-xs ph-no-capture">
                    {tasks.map((task) => (
                        <li key={task.name} className="flex items-start gap-2">
                            <span className="shrink-0 text-muted" aria-hidden>
                                {task.status === 'completed'
                                    ? '✓'
                                    : task.status === 'failed'
                                      ? '×'
                                      : task.status === 'running'
                                        ? '●'
                                        : '○'}
                            </span>
                            <span className="min-w-0 break-words">{task.name}</span>
                            <span className="sr-only">({task.status})</span>
                        </li>
                    ))}
                </ul>
            )}
            {activeCount > 1 && (
                <div className="border-t border-primary px-3.5 py-2 text-xs text-muted">
                    {activeCount} runs in progress. Showing the newest run.
                </div>
            )}
        </div>
    )
}
