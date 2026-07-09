import { Suspense } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { lazyWithRetry } from 'lib/utils/lazyWithRetry'

import type { TaskTrackerProps } from '../scenes/TaskTracker/TaskTracker'

export type { TaskTrackerProps } from '../scenes/TaskTracker/TaskTracker'

// The TaskTracker scene (master/detail list + composer + run detail) is the heavy runner UI. It's loaded on
// demand so a consumer that only links to it — e.g. the Max scene rendering it behind the sandbox view
// toggle — doesn't statically pull it into its own chunk. Only `react` + a lightweight spinner load eagerly.
const Lazy = lazyWithRetry(() => import('../scenes/TaskTracker/TaskTracker').then((m) => ({ default: m.TaskTracker })))

/**
 * Embeddable, code-split TaskTracker runner. Renders the standalone `/tasks` product (tasks list + composer
 * + agent-run detail) inside any host. Pass `taskId` to preselect a task; omit it for the list + composer.
 * Note the scene routes task selection/creation through its own `/tasks/:id` URLs.
 */
export function EmbeddedRunner(props: TaskTrackerProps): JSX.Element {
    return (
        <Suspense
            fallback={
                <div className="flex flex-1 items-center justify-center">
                    <Spinner className="text-2xl" />
                </div>
            }
        >
            <Lazy {...props} />
        </Suspense>
    )
}
