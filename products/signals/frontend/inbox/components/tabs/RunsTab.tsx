import { IconBrain } from '@posthog/icons'

import { SignalRun } from '../../types'
import { CardSkeleton } from '../cards/CardSkeleton'
import { isRunLive, RunStatusIndicator } from '../cards/runStatusVariant'
import { SignalRunCard } from '../cards/SignalRunCard'

/**
 * Runs panel: the project's scout and signals-pipeline tasks, split into what's happening now ("Live")
 * and what's already finished ("Past"). Each row links out to the standalone Tasks scene.
 * `inboxSceneLogic` merges the two sources newest-first, so each section stays newest-first too. A
 * skeleton covers the first load so the empty state doesn't flash before any data has been fetched.
 */
export function RunsTab({ runs, loading }: { runs: SignalRun[]; loading: boolean }): JSX.Element {
    const liveRuns: SignalRun[] = []
    const pastRuns: SignalRun[] = []
    for (const run of runs) {
        ;(isRunLive(run.status) ? liveRuns : pastRuns).push(run)
    }

    return (
        <div className="mx-auto max-w-3xl flex flex-col gap-5 px-6 py-4">
            {loading ? (
                <CardSkeleton count={4} variant="cards" />
            ) : runs.length === 0 ? (
                <div className="mx-auto max-w-md flex flex-col items-center text-center py-16 gap-2">
                    <div className="flex size-10 items-center justify-center rounded-full bg-fill-primary text-secondary mb-1">
                        <IconBrain className="text-2xl" />
                    </div>
                    <h3 className="text-base font-semibold m-0">No runs yet</h3>
                    <p className="text-sm text-tertiary m-0">Scout and agent runs will appear here.</p>
                </div>
            ) : (
                <>
                    <RunsSection
                        title="Live"
                        count={liveRuns.length}
                        isLive
                        runs={liveRuns}
                        empty={{
                            title: 'No active runs',
                            description: 'New runs appear here when scouts or agents start working.',
                        }}
                    />
                    {pastRuns.length > 0 && <RunsSection title="Past" count={pastRuns.length} runs={pastRuns} />}
                </>
            )}
        </div>
    )
}

interface RunsSectionProps {
    title: string
    count: number
    isLive?: boolean
    runs: SignalRun[]
    empty?: { title: string; description: string }
}

function RunsSection({ title, count, isLive, runs, empty }: RunsSectionProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 cursor-default select-none">
                <span className="font-semibold text-sm text-default">{title}</span>
                <span className="text-xs text-tertiary tabular-nums">{count}</span>
                {isLive && count > 0 ? <RunStatusIndicator variant="live" showLabel={false} /> : null}
            </div>
            {runs.length === 0 && empty ? (
                <div className="flex items-center gap-3 cursor-default select-none rounded border border-dashed border-primary bg-surface-secondary px-4 py-3.5">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-fill-primary ring-1 ring-inset ring-primary">
                        <IconBrain className="text-tertiary" />
                    </div>
                    <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                        <span className="font-medium text-sm text-default">{empty.title}</span>
                        <span className="text-xs text-tertiary leading-snug">{empty.description}</span>
                    </div>
                </div>
            ) : (
                <div className="flex flex-col gap-3">
                    {runs.map((run) => (
                        <SignalRunCard key={run.task_id} run={run} />
                    ))}
                </div>
            )}
        </div>
    )
}
