import { useActions, useValues } from 'kea'

import { Button, Skeleton, Text } from '@posthog/quill'

import { WorkThreadView } from '~/layout/today/workThread/WorkThreadView'

import { ReleaseRow } from './releaseUtils'
import { ReleaseWorkThreadEvidence } from './ReleaseWorkThreadEvidence'
import { releaseWorkThreadLogic } from './releaseWorkThreadLogic'

const SKELETON_STEPS = 3

export function ReleaseWorkThreadCard({ row }: { row: ReleaseRow }): JSX.Element | null {
    const logic = releaseWorkThreadLogic({ releaseId: row.id })
    const { thread, threadLoading, threadFailed } = useValues(logic)
    const { loadReleaseWorkThread, runAction } = useActions(logic)

    // A reload after a change keeps the thread on screen, so only the first load shows the skeleton.
    if (threadLoading && !thread) {
        return (
            <div className="flex flex-col gap-4" data-attr="release-work-thread-loading">
                <Skeleton className="h-4 w-48" />
                <div className="flex flex-col gap-3">
                    {Array.from({ length: SKELETON_STEPS }, (_, index) => (
                        <div key={index} className="flex gap-3">
                            <Skeleton className="mt-2.5 size-6 shrink-0 rounded-full" />
                            <Skeleton className="h-16 min-w-0 flex-1" />
                        </div>
                    ))}
                </div>
            </div>
        )
    }

    if (threadFailed) {
        return (
            <div className="flex flex-wrap items-center gap-2" data-attr="release-work-thread-failed">
                <Text size="xs" variant="muted">
                    The next steps could not load.
                </Text>
                <Button
                    size="xs"
                    variant="outline"
                    onClick={() => loadReleaseWorkThread()}
                    data-attr="release-work-thread-retry"
                >
                    Try again
                </Button>
            </div>
        )
    }

    if (!thread) {
        return null
    }

    return (
        <WorkThreadView
            thread={thread}
            renderEvidence={(step) => (step.item ? <ReleaseWorkThreadEvidence step={step} row={row} /> : null)}
            onRunAction={(actionId, params) => runAction(actionId, params)}
        />
    )
}
