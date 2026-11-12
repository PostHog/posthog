import { useActions, useValues } from 'kea'

import { IconRefresh, IconSearch } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import type { TransactionalPushLogEntryApi } from 'products/messaging/frontend/generated/api.schemas'

import { transactionalTemplatesLogic } from '../transactionalTemplatesLogic'
import { PUSH_STATUS_DESCRIPTION, PUSH_STATUS_LABEL, PUSH_STATUS_TAG } from './pushLogStatus'
import { TransactionalEmailLogDateFilter } from './TransactionalEmailLogDateFilter'
import { transactionalPushLogLogic } from './transactionalPushLogLogic'

const STATUS_OPTIONS = (['sent', 'not_sent', 'failed', 'sending'] as const).map((status) => ({
    value: status,
    label: PUSH_STATUS_LABEL[status],
}))

export function TransactionalPushLog(): JSX.Element {
    const { pushes, pageLoading, pageFailed, filters, isFiltered, pagination } = useValues(transactionalPushLogLogic)
    const { setFilters, setPage, refresh, loadPushes } = useActions(transactionalPushLogLogic)
    const { sendablePushTemplates } = useValues(transactionalTemplatesLogic)

    const pushOptions = sendablePushTemplates.map((template) => ({
        value: template.transactional_hog_flow_id as string,
        label: template.name || 'Unnamed push notification',
    }))

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2 justify-between">
                <div className="flex items-center gap-2 flex-1 min-w-60">
                    <LemonInput
                        type="search"
                        size="small"
                        placeholder="Search by distinct ID"
                        fullWidth
                        value={filters.search}
                        onChange={(search) => setFilters({ search })}
                        prefix={<IconSearch />}
                        allowClear
                        data-attr="transactional-push-log-search"
                    />
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonSelect
                        size="small"
                        dropdownMatchSelectWidth={false}
                        value={filters.workflowId}
                        onChange={(workflowId) => setFilters({ workflowId })}
                        options={[{ value: null, label: 'All push notifications' }, ...pushOptions]}
                        data-attr="transactional-push-log-push-filter"
                    />
                    <LemonSelect
                        size="small"
                        dropdownMatchSelectWidth={false}
                        value={filters.status}
                        onChange={(status) => setFilters({ status })}
                        options={[{ value: null, label: 'Any status' }, ...STATUS_OPTIONS]}
                        data-attr="transactional-push-log-status-filter"
                    />
                    <TransactionalEmailLogDateFilter />
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconRefresh />}
                        loading={pageLoading}
                        onClick={() => refresh()}
                        data-attr="transactional-push-log-refresh"
                    >
                        Refresh
                    </LemonButton>
                </div>
            </div>
            {pageFailed && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadPushes(),
                        'data-attr': 'transactional-push-log-retry',
                    }}
                >
                    The log couldn't load. Check your connection and try again.
                </LemonBanner>
            )}
            <LemonTable<TransactionalPushLogEntryApi>
                dataSource={pushes}
                loading={pageLoading}
                rowKey="run_id"
                pagination={{
                    ...pagination,
                    onBackward:
                        pagination.currentPage && pagination.currentPage > 1
                            ? () => setPage(filters.page - 1)
                            : undefined,
                    onForward: pagination.entryCountIsLowerBound ? () => setPage(filters.page + 1) : undefined,
                }}
                nouns={['send', 'sends']}
                data-attr="transactional-push-log-table"
                expandable={{
                    rowExpandable: (push) => push.messages.length > 0,
                    expandedRowRender: (push) => (
                        <ul className="flex flex-col gap-1 px-4 py-2 ph-no-capture">
                            {push.messages.map((message, index) => (
                                <li key={index} className="break-words">
                                    {message}
                                </li>
                            ))}
                        </ul>
                    ),
                }}
                columns={[
                    {
                        title: 'Recipient',
                        key: 'recipient',
                        render: (_, push) => (
                            <LemonTableLink
                                to={urls.personByDistinctId(push.distinct_id)}
                                title={<span className="break-all">{push.distinct_id}</span>}
                                className="ph-no-capture"
                            />
                        ),
                    },
                    {
                        title: 'Push notification',
                        key: 'template',
                        render: (_, push) =>
                            push.template_id ? (
                                <LemonTableLink
                                    to={urls.transactionalPush(push.template_id)}
                                    title={push.template_name || 'Unnamed push notification'}
                                />
                            ) : (
                                <span className="text-secondary">Deleted push notification</span>
                            ),
                    },
                    {
                        title: 'Title',
                        key: 'title',
                        render: (_, push) =>
                            push.title ? (
                                <span className="ph-no-capture">{push.title}</span>
                            ) : (
                                <span className="text-secondary">–</span>
                            ),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        width: 0,
                        render: (_, push) => (
                            <Tooltip
                                title={
                                    push.messages.length > 0
                                        ? `${PUSH_STATUS_DESCRIPTION[push.status]} Expand the row to see what it logged.`
                                        : PUSH_STATUS_DESCRIPTION[push.status]
                                }
                            >
                                <LemonTag type={PUSH_STATUS_TAG[push.status]} className="whitespace-nowrap">
                                    {PUSH_STATUS_LABEL[push.status]}
                                </LemonTag>
                            </Tooltip>
                        ),
                    },
                    {
                        title: 'Sent',
                        key: 'created_at',
                        width: 0,
                        render: (_, push) => <TZLabel time={push.created_at} className="whitespace-nowrap" />,
                    },
                ]}
                emptyState={
                    pageFailed
                        ? "The log couldn't load"
                        : filters.page > 1
                          ? 'No more sends past this page. Go back a page to see the rest.'
                          : isFiltered
                            ? 'No sends match these filters'
                            : 'No push notifications sent in this period. Sends from your code show up here within a few seconds.'
                }
            />
        </div>
    )
}
