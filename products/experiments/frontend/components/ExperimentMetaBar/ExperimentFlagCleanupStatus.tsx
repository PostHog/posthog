import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { flagCleanupTaskLogic } from 'scenes/experiments/ExperimentView/flagCleanupTaskLogic'
import { urls } from 'scenes/urls'

export function ExperimentFlagCleanupStatus({
    experimentId,
    taskId,
}: {
    experimentId: number
    taskId: string
}): JSX.Element | null {
    const { cleanupTask } = useValues(flagCleanupTaskLogic({ experimentId }))

    if (!cleanupTask) {
        return null
    }

    let text = 'Preparing cleanup PR…'
    let prUrl: string | null = null
    if (cleanupTask.is_terminal) {
        if (cleanupTask.run_status === 'completed' && cleanupTask.pr_url) {
            text = 'Cleanup PR opened'
            prUrl = cleanupTask.pr_url
        } else if (cleanupTask.run_status === 'completed') {
            text = 'Cleanup found no flag code to remove'
        } else if (cleanupTask.run_status === 'failed') {
            text = 'Cleanup PR failed'
        } else {
            text = 'Cleanup PR canceled'
        }
    }

    const isExternalLink = prUrl !== null
    // The task page 404s for everyone but the task's creator, so hide the internal link from others.
    const showLink = isExternalLink || cleanupTask.can_view_task

    return (
        <div className="flex flex-wrap items-center gap-x-1.5 text-sm" data-attr="experiment-flag-cleanup">
            <span className="text-secondary">Flag cleanup</span>
            <span className="text-secondary">·</span>
            <span>{text}</span>
            {showLink && (
                <Link
                    target={isExternalLink ? '_blank' : undefined}
                    className="flex items-center gap-0.5"
                    to={prUrl ?? urls.taskDetail(taskId)}
                >
                    {isExternalLink ? (
                        <>
                            View on GitHub <IconOpenInNew fontSize="14" />
                        </>
                    ) : (
                        'View task'
                    )}
                </Link>
            )}
        </div>
    )
}
