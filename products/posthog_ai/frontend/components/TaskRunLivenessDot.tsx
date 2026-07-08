import { TaskRunStatus } from '../types/taskTypes'
import { TERMINAL_STATUSES } from './TaskRunStatusDot'

/** Pulsing green dot while the task's sandbox is live; renders nothing once the run is terminal. */
export function TaskRunLivenessDot({ status }: { status: TaskRunStatus }): JSX.Element | null {
    if (TERMINAL_STATUSES.includes(status)) {
        return null
    }
    return <span className="inline-block size-1.5 shrink-0 rounded-full bg-success animate-pulse" aria-hidden />
}
