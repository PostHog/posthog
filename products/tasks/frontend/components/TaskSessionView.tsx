import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { DropZone } from '../composer/DropZone'
import { PermissionRequestView } from '../composer/PermissionRequestView'
import { TaskComposer } from '../composer/TaskComposer'
import { taskComposerLogic } from '../composer/taskComposerLogic'
import type { AcpMessage } from '../conversation/acp-types'
import { type ConversationItem } from '../conversation/buildConversationItems'
import CloudInitializingView from '../conversation/CloudInitializingView'
import { deriveContextUsage } from '../conversation/contextUsage'
import { ContextUsageIndicator } from '../conversation/ContextUsageIndicator'
import { ConversationView } from '../conversation/ConversationView'
import { derivePlan } from '../conversation/derivePlan'
import { PlanStatusBar } from '../conversation/PlanStatusBar'
import { SessionResourcesBar } from '../conversation/SessionResourcesBar'
import StreamStatusBanner from '../conversation/StreamStatusBanner'
import { ReviewPanel } from '../review/ReviewPanel'
import { TaskRun, TaskRunStatus } from '../types'

interface TaskSessionViewProps {
    taskId: string
    logs: string
    logsLoading: boolean
    /** Parsed ACP events (stream-first, S3 fallback) produced by the scene logic. */
    events: AcpMessage[]
    isPolling: boolean
    isStreaming: boolean
    run: TaskRun | null
    streamingFailed: boolean
    onRetryStream: () => void
}

export function TaskSessionView({
    taskId,
    logsLoading,
    events,
    run,
    streamingFailed,
    onRetryStream,
}: TaskSessionViewProps): JSX.Element {
    const composer = taskComposerLogic({ taskId })
    const { firstPendingPermission, queuedMessages, visibleOptimisticItems, agentBusy } = useValues(composer)
    const { addFiles, respondToPermission } = useActions(composer)
    const [activeTab, setActiveTab] = useState<'conversation' | 'changes'>('conversation')

    const optimisticItems = useMemo<ConversationItem[]>(
        () =>
            visibleOptimisticItems.map((item) => ({
                type: 'user_message' as const,
                id: item.id,
                content: item.content,
                timestamp: item.timestamp,
                pinToTop: false,
            })),
        [visibleOptimisticItems]
    )

    const contextUsage = useMemo(() => deriveContextUsage(events), [events])
    const latestPlan = useMemo(() => derivePlan(events), [events])

    const footer = firstPendingPermission ? (
        <PermissionRequestView
            permission={firstPendingPermission}
            onRespond={(optionId, customInput) =>
                respondToPermission(firstPendingPermission.requestId, optionId, customInput)
            }
        />
    ) : (
        <TaskComposer taskId={taskId} />
    )

    const hasContent = events.length > 0 || optimisticItems.length > 0 || queuedMessages.length > 0
    const isInitializing = run?.status === TaskRunStatus.QUEUED || run?.status === TaskRunStatus.IN_PROGRESS

    return (
        <DropZone onDropFiles={addFiles} className="flex flex-col h-full min-h-0">
            <div className="flex shrink-0 items-center border-b px-4 py-1">
                <LemonSegmentedButton
                    size="xsmall"
                    value={activeTab}
                    onChange={(value) => setActiveTab(value)}
                    options={[
                        { value: 'conversation' as const, label: 'Conversation' },
                        { value: 'changes' as const, label: 'Changes' },
                    ]}
                />
            </div>
            <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
                {streamingFailed && events.length > 0 && <StreamStatusBanner onRetry={onRetryStream} />}
                <div className="flex-1 min-h-0 overflow-hidden">
                    {activeTab === 'changes' ? (
                        <ReviewPanel run={run} events={events} />
                    ) : hasContent ? (
                        <ConversationView
                            events={events}
                            isPromptPending={agentBusy}
                            queuedMessages={queuedMessages}
                            optimisticItems={optimisticItems}
                            isCloud
                        />
                    ) : isInitializing ? (
                        <CloudInitializingView run={run} />
                    ) : logsLoading ? (
                        <div className="flex items-center justify-center h-32">
                            <Spinner />
                        </div>
                    ) : (
                        <div className="p-4 text-center text-muted">
                            <p>No logs available yet</p>
                        </div>
                    )}
                </div>
            </div>
            {activeTab === 'conversation' && (
                <>
                    <PlanStatusBar plan={latestPlan} />
                    <div className="border-t px-4 py-3">
                        <SessionResourcesBar events={events} />
                        {contextUsage && (
                            <div className="flex justify-end mb-1">
                                <ContextUsageIndicator usage={contextUsage} />
                            </div>
                        )}
                        {footer}
                    </div>
                </>
            )}
        </DropZone>
    )
}
