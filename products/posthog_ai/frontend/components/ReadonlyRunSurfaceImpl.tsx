import { cn } from 'lib/utils/css-classes'

import { RunSurface } from './RunSurfaceImpl'

export interface ReadonlyRunSurfaceProps {
    taskId: string
    runId: string
    /** `'read-only'` (default) replays the snapshot once; `'live'` streams over SSE while the run is in progress. */
    interaction?: 'live' | 'read-only'
    threadListClassName?: string
    threadRowClassName?: string
    className?: string
}

/**
 * Prepackaged read-only run surface — the common inbox embed, owned by the library. Composes the
 * `RunSurface` compound and never renders `<RunSurface.Composer>`, so there is no composer and no approval
 * prompt (you don't act on a run from the inbox). It still streams fresh frames while the run is in progress
 * when `interaction='live'`, surfacing the resources bar (context usage rides the thread footer between
 * turns); a terminal run replays the snapshot once and shows only the thread.
 */
export default function ReadonlyRunSurfaceImpl({
    taskId,
    runId,
    interaction = 'read-only',
    threadListClassName,
    threadRowClassName,
    className,
}: ReadonlyRunSurfaceProps): JSX.Element {
    return (
        <RunSurface.Root taskId={taskId} runId={runId} interaction={interaction}>
            {interaction !== 'live' ? (
                <div className={cn('flex flex-col h-full min-h-0 w-full', className)}>
                    <RunSurface.Thread listClassName={threadListClassName} rowClassName={threadRowClassName} />
                </div>
            ) : (
                <div className={cn('@container/thread flex flex-col h-full overflow-hidden', className)}>
                    <div className="flex-1 min-h-0">
                        <RunSurface.Thread listClassName={threadListClassName} rowClassName={threadRowClassName} />
                    </div>
                    <RunSurface.Resources />
                </div>
            )}
        </RunSurface.Root>
    )
}
