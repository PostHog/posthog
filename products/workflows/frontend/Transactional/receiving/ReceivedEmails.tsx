import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconDocument, IconRefresh, IconSearch } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { INVOCATIONS_DATE_OPTIONS } from 'scenes/hog-functions/invocations/invocationsDateOptions'
import { urls } from 'scenes/urls'

import type { ReceivedEmailApi } from 'products/workflows/frontend/generated/api.schemas'

import { EmailAddress } from '../log/EmailAddress'
import { inboundEmailDomainsLogic } from './inboundEmailDomainsLogic'
import { FILTER_REASON_DESCRIPTION, FILTER_REASON_LABEL, senderLabel } from './receivedEmailLabels'
import {
    DEFAULT_RECEIVED_FILTERS,
    RECEIVED_RETENTION_DAYS,
    ReceivedStatusFilter,
    receivedEmailsLogic,
} from './receivedEmailsLogic'
import { ReceivingAddress } from './ReceivingAddress'
import { ReceivingDomainsModal } from './ReceivingDomainsModal'
import { ReceivingSetup } from './ReceivingSetup'

// The Webhooks tab reaches users through its own flag, so the link appears when that tab does.
const DELIVERY_WEBHOOKS_FLAG = 'workflows-email-delivery-webhooks'

const STATUS_OPTIONS: { value: ReceivedStatusFilter; label: string }[] = [
    { value: 'received', label: 'Received' },
    { value: 'filtered', label: 'Filtered' },
    { value: 'all', label: 'All' },
]

export function ReceivedEmails(): JSX.Element {
    const { emails, pageLoading, pageFailed, filters, isFiltered, pagination, filteredCount, isWaitingForMail } =
        useValues(receivedEmailsLogic)
    const { setFilters, setPage, refresh, loadEmails } = useActions(receivedEmailsLogic)
    const { generatedDomain, customDomains, limitReachedAt } = useValues(inboundEmailDomainsLogic)
    const { openDomains } = useActions(inboundEmailDomainsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const webhooksAvailable = !!featureFlags[DELIVERY_WEBHOOKS_FLAG as keyof typeof featureFlags]

    const activeCustom = customDomains.filter((domain) => domain.status === 'active')
    const shownDomain = generatedDomain ?? activeCustom[0]
    const otherAddresses = customDomains.length + (generatedDomain ? 1 : 0) - (shownDomain ? 1 : 0)

    return (
        <div className="flex flex-col gap-3" data-attr="received-email-view">
            <ReceivingDomainsModal />
            {limitReachedAt && (
                <LemonBanner type="warning">
                    Mail went over this project's daily limit on <TZLabel time={limitReachedAt} />, and the emails over
                    it were dropped. Contact support if you need a higher limit.
                </LemonBanner>
            )}
            {isWaitingForMail ? (
                <ReceivingSetup />
            ) : (
                <>
                    <div className="flex flex-wrap items-center justify-between gap-2 border rounded bg-surface-primary px-3 py-2">
                        <div className="flex flex-wrap items-center gap-2 min-w-0 text-sm">
                            <span className="text-secondary">Receiving at</span>
                            {shownDomain ? (
                                <ReceivingAddress domain={shownDomain.domain} />
                            ) : (
                                <span className="text-secondary">No address yet</span>
                            )}
                        </div>
                        <div className="flex items-center gap-2">
                            {webhooksAvailable && (
                                <LemonButton
                                    size="small"
                                    to={`${urls.transactional()}/webhooks`}
                                    data-attr="received-email-add-webhook"
                                >
                                    Add webhook
                                </LemonButton>
                            )}
                            <LemonButton
                                size="small"
                                to={urls.workflowNew()}
                                tooltip='Start a workflow from the "Email received" event'
                                data-attr="received-email-create-workflow"
                            >
                                Create workflow
                            </LemonButton>
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => openDomains()}
                                data-attr="received-email-manage-addresses"
                            >
                                {otherAddresses > 0 ? `Addresses (${otherAddresses + 1})` : 'Addresses'}
                            </LemonButton>
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 justify-between">
                        <div className="flex items-center gap-2 flex-1 min-w-60">
                            <LemonInput
                                type="search"
                                size="small"
                                placeholder="Search by sender, subject or recipient"
                                fullWidth
                                value={filters.search}
                                onChange={(search) => setFilters({ search })}
                                prefix={<IconSearch />}
                                allowClear
                                data-attr="received-email-search"
                            />
                        </div>
                        <div className="flex items-center gap-2 flex-wrap">
                            <LemonSelect
                                size="small"
                                dropdownMatchSelectWidth={false}
                                value={filters.status}
                                onChange={(status) => setFilters({ status })}
                                options={STATUS_OPTIONS}
                                data-attr="received-email-status-filter"
                            />
                            <DateFilter
                                size="small"
                                dateFrom={filters.dateFrom}
                                dateTo={filters.dateTo ?? undefined}
                                onChange={(dateFrom, dateTo) =>
                                    setFilters({
                                        dateFrom: dateFrom || DEFAULT_RECEIVED_FILTERS.dateFrom,
                                        dateTo: dateTo || null,
                                    })
                                }
                                dateOptions={INVOCATIONS_DATE_OPTIONS}
                                allowTimePrecision
                                allowFixedRangeWithTime
                                allowedRollingDateOptions={['minutes', 'hours', 'days', 'weeks']}
                                max={RECEIVED_RETENTION_DAYS}
                                use24HourFormat
                                data-attr="received-email-date-filter"
                            />
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconRefresh />}
                                loading={pageLoading}
                                onClick={() => refresh()}
                                data-attr="received-email-refresh"
                            >
                                Refresh
                            </LemonButton>
                        </div>
                    </div>
                    {filters.status === 'received' && filteredCount > 0 && (
                        <button
                            type="button"
                            className="text-sm text-secondary text-left underline cursor-pointer bg-transparent border-0 p-0 w-fit"
                            onClick={() => setFilters({ status: 'filtered' })}
                            data-attr="received-email-show-filtered"
                        >
                            {filteredCount} filtered {filteredCount === 1 ? 'email' : 'emails'} in this period, such as
                            spam and auto-replies
                        </button>
                    )}
                    {pageFailed && (
                        <LemonBanner
                            type="error"
                            action={{
                                children: 'Try again',
                                onClick: () => loadEmails(),
                                'data-attr': 'received-email-retry',
                            }}
                        >
                            Received email couldn't load. Check your connection and try again.
                        </LemonBanner>
                    )}
                    <LemonTable<ReceivedEmailApi>
                        dataSource={emails}
                        loading={pageLoading}
                        rowKey="id"
                        nouns={['email', 'emails']}
                        data-attr="received-email-table"
                        pagination={{
                            ...pagination,
                            onBackward:
                                pagination.currentPage && pagination.currentPage > 1
                                    ? () => setPage(filters.page - 1)
                                    : undefined,
                            onForward: pagination.entryCountIsLowerBound ? () => setPage(filters.page + 1) : undefined,
                        }}
                        onRow={(email) => ({
                            onClick: () => router.actions.push(urls.transactionalReceivedEmail(email.id)),
                            className: 'cursor-pointer',
                        })}
                        columns={[
                            {
                                title: 'From',
                                key: 'from',
                                render: (_, email) => (
                                    <LemonTableLink
                                        to={urls.transactionalReceivedEmail(email.id)}
                                        title={senderLabel(email)}
                                        description={
                                            email.from_name ? <EmailAddress address={email.from_address} /> : undefined
                                        }
                                        className="ph-no-capture"
                                        onClick={(event) => event.stopPropagation()}
                                    />
                                ),
                            },
                            {
                                title: 'To',
                                key: 'to',
                                render: (_, email) => (
                                    <span className="ph-no-capture">
                                        <EmailAddress address={email.envelope_recipients[0] ?? ''} />
                                        {email.envelope_recipients.length > 1
                                            ? ` +${email.envelope_recipients.length - 1}`
                                            : ''}
                                    </span>
                                ),
                            },
                            {
                                title: 'Subject',
                                key: 'subject',
                                width: '35%',
                                render: (_, email) => (
                                    <div className="ph-no-capture flex items-center gap-1.5 min-w-0">
                                        <span className="truncate max-w-[32rem]">
                                            {email.subject || <span className="text-secondary">(no subject)</span>}
                                        </span>
                                        {email.attachment_count > 0 && (
                                            <Tooltip
                                                title={`${email.attachment_count} ${email.attachment_count === 1 ? 'attachment' : 'attachments'}`}
                                            >
                                                <IconDocument className="text-secondary shrink-0" />
                                            </Tooltip>
                                        )}
                                    </div>
                                ),
                            },
                            {
                                title: 'Status',
                                key: 'status',
                                width: 0,
                                render: (_, email) => (
                                    <div className="flex items-center gap-1 flex-wrap">
                                        {email.status === 'filtered' && (
                                            <Tooltip title={FILTER_REASON_DESCRIPTION[email.filter_reason]}>
                                                <LemonTag type="warning" className="whitespace-nowrap">
                                                    {FILTER_REASON_LABEL[email.filter_reason] ?? 'Filtered'}
                                                </LemonTag>
                                            </Tooltip>
                                        )}
                                        {!email.sender_verified && (
                                            <Tooltip title="We couldn't prove this email came from the address it shows. The sender may be forged.">
                                                <LemonTag type="muted" className="whitespace-nowrap">
                                                    Unverified sender
                                                </LemonTag>
                                            </Tooltip>
                                        )}
                                    </div>
                                ),
                            },
                            {
                                title: 'Received',
                                key: 'received_at',
                                width: 0,
                                render: (_, email) => (
                                    <TZLabel time={email.received_at} className="whitespace-nowrap" />
                                ),
                            },
                        ]}
                        emptyState={
                            pageFailed
                                ? "Received email couldn't load"
                                : filters.page > 1
                                  ? 'No more emails past this page. Go back a page to see the rest.'
                                  : isFiltered
                                    ? 'No emails match these filters'
                                    : 'No email received in this period. Try a wider date range.'
                        }
                    />
                </>
            )}
        </div>
    )
}
