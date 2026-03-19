import { useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import {
    LemonButton,
    LemonInput,
    LemonModal,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
    LemonTag,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonModalContent, LemonModalFooter, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'

import { createdAtColumn } from '~/lib/lemon-ui/LemonTable/columnUtils'
import { urls } from '~/scenes/urls'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ReviewQueueApi, ReviewQueueItemApi } from '../generated/api.schemas'
import {
    llmAnalyticsReviewQueuesLogic,
    REVIEW_QUEUE_ITEMS_PER_PAGE,
    REVIEW_QUEUES_PER_PAGE,
} from './llmAnalyticsReviewQueuesLogic'

export function LLMAnalyticsReviewQueues({ tabId }: { tabId?: string }): JSX.Element {
    const logic = useMountedLogic(llmAnalyticsReviewQueuesLogic({ tabId }))
    const {
        setQueueFilters,
        setQueueItemFilters,
        selectQueue,
        openQueueEditor,
        closeQueueEditor,
        setQueueEditorName,
        submitQueueEditor,
        requestDeleteQueue,
        requestRemoveQueueItem,
    } = useActions(logic)
    const {
        queues,
        queuesLoading,
        visibleQueues,
        queueFilters,
        queueSorting,
        queuePagination,
        queueCountLabel,
        selectedQueueId,
        activeQueue,
        queueItems,
        queueItemsLoading,
        queueItemFilters,
        queueItemSorting,
        queueItemPagination,
        queueItemCountLabel,
        queueEditorMode,
        queueEditorTitle,
        queueEditorName,
        queueEditorSubmitting,
        hasLoadedQueuesOnce,
    } = useValues(logic)
    const { searchParams } = useValues(router)

    const queueColumns: LemonTableColumns<ReviewQueueApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            width: '72%',
            render: function renderQueueName(_, queue) {
                return (
                    <div className="space-y-1 min-w-0">
                        <div className="font-semibold whitespace-normal break-words">{queue.name}</div>
                        <div className="text-xs text-muted">{queue.pending_item_count} pending traces</div>
                    </div>
                )
            },
        },
        {
            title: 'Pending',
            dataIndex: 'pending_item_count',
            key: 'pending_item_count',
            align: 'right',
            render: function renderPendingCount(_, queue) {
                return <span className="font-medium">{queue.pending_item_count}</span>
            },
        },
    ]

    const queueItemColumns: LemonTableColumns<ReviewQueueItemApi> = [
        {
            title: 'Trace',
            dataIndex: 'trace_id',
            key: 'trace_id',
            width: '45%',
            render: function renderTraceId(traceId, item) {
                const value = String(traceId || '')
                const currentIndex = queueItems.results.findIndex((queueItem) => queueItem.id === item.id)
                const nextTraceId = currentIndex >= 0 ? queueItems.results[currentIndex + 1]?.trace_id : undefined

                return (
                    <Link
                        to={
                            combineUrl(urls.llmAnalyticsTrace(value), {
                                ...searchParams,
                                back_to: 'reviews',
                                human_reviews_tab: undefined,
                                queue_id: selectedQueueId || undefined,
                                queue_next_trace_id: nextTraceId,
                            }).url
                        }
                        className="font-mono text-xs"
                    >
                        {value}
                    </Link>
                )
            },
        },
        {
            title: 'Created by',
            dataIndex: 'created_by',
            key: 'created_by',
            render: function renderCreatedBy(_, item) {
                const createdBy = item.created_by

                return (
                    <div className="flex flex-row items-center flex-nowrap">
                        <ProfilePicture
                            user={{
                                first_name: createdBy.first_name,
                                last_name: createdBy.last_name,
                                email: createdBy.email,
                            }}
                            size="md"
                            showName
                        />
                    </div>
                )
            },
            sorter: (a, b) =>
                (a.created_by.first_name || a.created_by.email || '').localeCompare(
                    b.created_by.first_name || b.created_by.email || ''
                ),
        },
        createdAtColumn<ReviewQueueItemApi>() as LemonTableColumn<
            ReviewQueueItemApi,
            keyof ReviewQueueItemApi | undefined
        >,
        {
            width: 0,
            render: function renderActions(_, item) {
                return (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <More
                            overlay={
                                <LemonButton status="danger" fullWidth onClick={() => requestRemoveQueueItem(item)}>
                                    Remove trace
                                </LemonButton>
                            }
                        />
                    </AccessControlAction>
                )
            },
        },
    ]

    const showEmptyQueueState = hasLoadedQueuesOnce && queues.count === 0 && !queuesLoading

    return (
        <div className="space-y-4">
            <div className="flex gap-x-4 gap-y-2 items-center flex-wrap py-4 mb-4 border-b justify-between">
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonInput
                        type="search"
                        placeholder="Search queues..."
                        value={queueFilters.search}
                        onChange={(value) => setQueueFilters({ search: value })}
                        className="min-w-64"
                        data-attr="llma-review-queues-search-input"
                    />
                    <div className="text-muted-alt">{queueCountLabel}</div>
                </div>

                <div className="flex items-center gap-2">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton type="secondary" size="small" onClick={() => openQueueEditor('create')}>
                            New queue
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </div>

            {showEmptyQueueState ? (
                <div className="border rounded bg-bg-light">
                    <InsightEmptyState
                        heading="No review queues yet"
                        detail="Create a queue, then add traces from the trace page when they need human review."
                    />
                    <div className="flex items-center justify-center gap-2 px-4 pb-6">
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton type="secondary" onClick={() => openQueueEditor('create')}>
                                New queue
                            </LemonButton>
                        </AccessControlAction>
                    </div>
                </div>
            ) : (
                <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(19rem,23rem)_minmax(0,1fr)]">
                    <div className="border rounded bg-bg-light">
                        <div className="px-4 pt-4 pb-3 text-sm font-medium">Queues</div>
                        <LemonTable
                            id="queue"
                            loading={queuesLoading}
                            columns={queueColumns}
                            dataSource={visibleQueues}
                            pagination={queuePagination}
                            sorting={queueSorting}
                            onSort={(newSorting) =>
                                setQueueFilters({
                                    order_by: newSorting
                                        ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                        : undefined,
                                })
                            }
                            useURLForSorting={false}
                            rowKey="id"
                            rowStatus={(queue) => (queue.id === selectedQueueId ? 'highlighted' : null)}
                            rowClassName="cursor-pointer"
                            onRow={(queue) => ({
                                onClick: () => selectQueue(queue.id),
                            })}
                            loadingSkeletonRows={REVIEW_QUEUES_PER_PAGE}
                            nouns={['queue', 'queues']}
                            emptyState={
                                <InsightEmptyState
                                    heading="No matching queues"
                                    detail="Try a different search or create a new queue."
                                />
                            }
                        />
                    </div>

                    <div className="border rounded bg-bg-light">
                        {activeQueue ? (
                            <div className="space-y-4 p-4">
                                <div className="flex gap-3 items-start justify-between flex-wrap">
                                    <div className="space-y-2 min-w-0">
                                        <div className="flex items-start gap-2.5 flex-wrap">
                                            <h3 className="text-lg leading-tight font-semibold truncate">
                                                {activeQueue.name}
                                            </h3>
                                            <LemonTag type="muted" className="mt-0.5 shrink-0">
                                                {activeQueue.pending_item_count} pending
                                            </LemonTag>
                                        </div>
                                        <div className="text-sm text-muted">
                                            Traces stay here until someone reviews them. Once reviewed, they leave the
                                            queue.
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-2">
                                        <AccessControlAction
                                            resourceType={AccessControlResourceType.LlmAnalytics}
                                            minAccessLevel={AccessControlLevel.Editor}
                                        >
                                            <More
                                                overlay={
                                                    <>
                                                        <LemonButton
                                                            fullWidth
                                                            onClick={() => openQueueEditor('rename', activeQueue)}
                                                        >
                                                            Rename queue
                                                        </LemonButton>
                                                        <LemonButton
                                                            status="danger"
                                                            fullWidth
                                                            onClick={() => requestDeleteQueue(activeQueue)}
                                                        >
                                                            Delete queue
                                                        </LemonButton>
                                                    </>
                                                }
                                            />
                                        </AccessControlAction>
                                    </div>
                                </div>

                                <div className="flex gap-x-4 gap-y-2 items-center flex-wrap justify-between">
                                    <LemonInput
                                        type="search"
                                        placeholder="Search pending traces..."
                                        value={queueItemFilters.search}
                                        onChange={(value) => setQueueItemFilters({ search: value })}
                                        className="min-w-64"
                                        data-attr="llma-review-queue-items-search-input"
                                    />
                                    <div className="text-muted-alt">{queueItemCountLabel}</div>
                                </div>

                                <LemonTable
                                    id="queue_item"
                                    loading={queueItemsLoading}
                                    columns={queueItemColumns}
                                    dataSource={queueItems.results}
                                    pagination={queueItemPagination}
                                    sorting={queueItemSorting}
                                    onSort={(newSorting) =>
                                        setQueueItemFilters({
                                            order_by: newSorting
                                                ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                                : undefined,
                                        })
                                    }
                                    useURLForSorting={false}
                                    rowKey="id"
                                    loadingSkeletonRows={REVIEW_QUEUE_ITEMS_PER_PAGE}
                                    nouns={['pending trace', 'pending traces']}
                                    emptyState={
                                        <div className="py-6">
                                            <InsightEmptyState
                                                heading="No pending traces in this queue"
                                                detail="Use Add to queue on a trace page to send it here."
                                            />
                                        </div>
                                    }
                                />
                            </div>
                        ) : (
                            <div className="p-4">
                                <InsightEmptyState
                                    heading="Select a queue"
                                    detail="Pick a queue from the left to see the pending traces assigned to it."
                                />
                            </div>
                        )}
                    </div>
                </div>
            )}

            {queueEditorMode ? (
                <LemonModal isOpen onClose={closeQueueEditor} simple maxWidth="28rem">
                    <LemonModalHeader>{queueEditorTitle}</LemonModalHeader>
                    <LemonModalContent className="space-y-4">
                        <div className="space-y-2">
                            <div className="text-sm font-medium">Queue name</div>
                            <LemonInput
                                value={queueEditorName}
                                onChange={(value) => setQueueEditorName(String(value || ''))}
                                placeholder="Support escalations"
                                autoFocus
                                fullWidth
                                data-attr="llma-review-queue-name-input"
                            />
                            <div className="text-xs text-muted">
                                Use a short, recognizable name so teammates know what belongs in this queue.
                            </div>
                        </div>
                    </LemonModalContent>
                    <LemonModalFooter>
                        <LemonButton type="secondary" onClick={closeQueueEditor} disabled={queueEditorSubmitting}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => submitQueueEditor()}
                            loading={queueEditorSubmitting}
                            disabledReason={!queueEditorName.trim() ? 'Queue name is required' : undefined}
                        >
                            {queueEditorMode === 'rename' ? 'Save queue' : 'Create queue'}
                        </LemonButton>
                    </LemonModalFooter>
                </LemonModal>
            ) : null}
        </div>
    )
}
