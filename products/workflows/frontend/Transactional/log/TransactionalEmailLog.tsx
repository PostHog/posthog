import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCursorClick, IconEye, IconRefresh, IconSearch } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import type { TransactionalEmailLogEntryApi } from 'products/messaging/frontend/generated/api.schemas'

import { messageTemplatesLogic } from '../../TemplateLibrary/messageTemplatesLogic'
import { EmailDirectionToggle } from '../comingSoon/EmailDirectionToggle'
import { EMAIL_STATUS_DESCRIPTION, EMAIL_STATUS_LABEL, EMAIL_STATUS_TAG, emailReasonText } from './emailLogStatus'
import { QuillTransactionalEmailLogFilters } from './QuillTransactionalEmailLogFilters'
import { TransactionalEmailLogDateFilter } from './TransactionalEmailLogDateFilter'
import { transactionalEmailLogLogic } from './transactionalEmailLogLogic'

/** Lets a long address wrap before its domain instead of mid-word. */
function EmailAddress({ address }: { address: string }): JSX.Element {
    if (!address) {
        return <span className="text-secondary">Unknown recipient</span>
    }
    const at = address.lastIndexOf('@')
    if (at <= 0) {
        return <span className="break-all">{address}</span>
    }
    return (
        <span className="break-words">
            {address.slice(0, at)}
            <wbr />
            {address.slice(at)}
        </span>
    )
}

const STATUS_OPTIONS = (['delivered', 'sent', 'queued', 'bounced', 'complained', 'failed'] as const).map((status) => ({
    value: status,
    label: EMAIL_STATUS_LABEL[status],
}))

export function TransactionalEmailLog(): JSX.Element {
    const { emails, pageLoading, pageFailed, filters, isFiltered, pagination } = useValues(transactionalEmailLogLogic)
    const { setFilters, setPage, refresh, loadEmails } = useActions(transactionalEmailLogLogic)
    const { transactionalTemplates } = useValues(messageTemplatesLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const emailOptions = transactionalTemplates
        .filter((template) => template.transactional_hog_flow_id)
        .map((template) => ({
            value: template.transactional_hog_flow_id as string,
            label: template.name || 'Unnamed email',
        }))

    return (
        <div className="flex flex-col gap-2">
            <EmailDirectionToggle />
            {todayRailNav ? (
                <QuillTransactionalEmailLogFilters emailOptions={emailOptions} statusOptions={STATUS_OPTIONS} />
            ) : (
                <div className="flex flex-wrap items-center gap-2 justify-between">
                    <div className="flex items-center gap-2 flex-1 min-w-60">
                        <LemonInput
                            type="search"
                            size="small"
                            placeholder="Search by recipient or message ID"
                            fullWidth
                            value={filters.search}
                            onChange={(search) => setFilters({ search })}
                            prefix={<IconSearch />}
                            allowClear
                            data-attr="transactional-email-log-search"
                        />
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                        <LemonSelect
                            size="small"
                            dropdownMatchSelectWidth={false}
                            value={filters.workflowId}
                            onChange={(workflowId) => setFilters({ workflowId })}
                            options={[{ value: null, label: 'All emails' }, ...emailOptions]}
                            data-attr="transactional-email-log-email-filter"
                        />
                        <LemonSelect
                            size="small"
                            dropdownMatchSelectWidth={false}
                            value={filters.status}
                            onChange={(status) => setFilters({ status })}
                            options={[{ value: null, label: 'Any status' }, ...STATUS_OPTIONS]}
                            data-attr="transactional-email-log-status-filter"
                        />
                        <TransactionalEmailLogDateFilter />
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconRefresh />}
                            loading={pageLoading}
                            onClick={() => refresh()}
                            data-attr="transactional-email-log-refresh"
                        >
                            Refresh
                        </LemonButton>
                    </div>
                </div>
            )}
            {pageFailed && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadEmails(),
                        'data-attr': 'transactional-email-log-retry',
                    }}
                >
                    The log couldn't load. Check your connection and try again.
                </LemonBanner>
            )}
            <LemonTable<TransactionalEmailLogEntryApi>
                dataSource={emails}
                loading={pageLoading}
                rowKey="message_id"
                pagination={{
                    ...pagination,
                    onBackward:
                        pagination.currentPage && pagination.currentPage > 1
                            ? () => setPage(filters.page - 1)
                            : undefined,
                    onForward: pagination.entryCountIsLowerBound ? () => setPage(filters.page + 1) : undefined,
                }}
                nouns={['send', 'sends']}
                data-attr="transactional-email-log-table"
                onRow={(email) => ({
                    onClick: () => router.actions.push(urls.transactionalEmailLogEntry(email.message_id)),
                    className: 'cursor-pointer',
                })}
                columns={[
                    {
                        title: 'Recipient',
                        key: 'recipient',
                        render: (_, email) => (
                            <LemonTableLink
                                to={urls.transactionalEmailLogEntry(email.message_id)}
                                title={<EmailAddress address={email.recipient} />}
                                className="ph-no-capture"
                                onClick={(event) => event.stopPropagation()}
                            />
                        ),
                    },
                    {
                        title: 'Email',
                        key: 'template',
                        render: (_, email) => (
                            <span className="whitespace-nowrap">
                                {email.template_name || <span className="text-secondary">Deleted email</span>}
                            </span>
                        ),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        width: 0,
                        render: (_, email) => (
                            <Tooltip title={emailReasonText(email.reason) ?? EMAIL_STATUS_DESCRIPTION[email.status]}>
                                <LemonTag type={EMAIL_STATUS_TAG[email.status]} className="whitespace-nowrap">
                                    {EMAIL_STATUS_LABEL[email.status]}
                                </LemonTag>
                            </Tooltip>
                        ),
                    },
                    {
                        title: 'Engagement',
                        key: 'engagement',
                        width: 0,
                        render: (_, email) =>
                            email.opened || email.clicked ? (
                                <div className="flex items-center gap-1">
                                    {email.opened && (
                                        <LemonTag icon={<IconEye />} className="whitespace-nowrap">
                                            Opened
                                        </LemonTag>
                                    )}
                                    {email.clicked && (
                                        <LemonTag icon={<IconCursorClick />} className="whitespace-nowrap">
                                            Clicked
                                        </LemonTag>
                                    )}
                                </div>
                            ) : null,
                    },
                    {
                        title: 'Sent',
                        key: 'created_at',
                        width: 0,
                        render: (_, email) => <TZLabel time={email.created_at} className="whitespace-nowrap" />,
                    },
                ]}
                emptyState={
                    pageFailed
                        ? "The log couldn't load"
                        : filters.page > 1
                          ? 'No more sends past this page. Go back a page to see the rest.'
                          : isFiltered
                            ? 'No sends match these filters'
                            : 'No transactional emails sent in this period. Sends from your code show up here within a few seconds.'
                }
            />
        </div>
    )
}
