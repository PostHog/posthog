import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconCode, IconLetter, IconLock } from '@posthog/icons'
import { LemonInput, LemonSelect, LemonTag, Link } from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TagSelect } from 'lib/components/TagSelect'
import { dayjs } from 'lib/dayjs'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { createdByColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { EmailMetricsIncidentBanner } from '../EmailMetricsIncidentBanner'
import { CodeBadge } from './code/CodeBadge'
import { ManagedBy, TransactionalEmailRow } from './transactionalEmailRows'
import { transactionalEmailsLogic } from './transactionalEmailsLogic'

// Below this width the table keeps only the name and the sparkline, so it fits beside an open side panel.
const COLUMN_BREAKPOINTS = { 0: 'narrow', 760: 'wide' } as const

export function TransactionalEmailsTable(): JSX.Element {
    const {
        transactionalTemplates,
        codeEmails,
        filteredTransactionalEmails,
        templatesLoading,
        codeEmailsLoading,
        filters,
        isFiltered,
        savingTagsFor,
    } = useValues(transactionalEmailsLogic)
    const { setFilters, saveTransactionalTags } = useActions(transactionalEmailsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { ref: widthRef, size } = useResizeBreakpoints(COLUMN_BREAKPOINTS, { initialSize: 'wide' })
    const wide = size === 'wide'
    // Same check as the "New transactional email" button: changing a template needs Editor access.
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor
    )

    if (!templatesLoading && transactionalTemplates.length === 0 && codeEmails?.length === 0) {
        return (
            <ProductIntroduction
                thingName="transactional email"
                description="Send emails from your code with one API call. Use them for emails a person triggers, like password resets, receipts and sign-in codes. This tab shows how many were sent, delivered and failed in the last 7 days."
                docsURL="https://posthog.com/docs/workflows"
                action={() => router.actions.push(urls.transactionalNew())}
                disabledReason={editDisabledReason ?? undefined}
                isEmpty
            />
        )
    }

    return (
        <div ref={widthRef} className="flex flex-col gap-2">
            {/* The sparklines read '-7d', which starts at midnight 7 days ago in the project's timezone. */}
            <EmailMetricsIncidentBanner
                dateFrom={dayjs()
                    .tz(currentTeam?.timezone ?? 'UTC')
                    .subtract(7, 'day')
                    .startOf('day')}
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search emails"
                    onChange={(search) => setFilters({ search })}
                    value={filters.search}
                    data-attr="transactional-emails-search"
                />
                <div className="flex flex-wrap items-center gap-2">
                    <span className="flex items-center gap-2">
                        <b>Managed by</b>
                        <LemonSelect<ManagedBy>
                            size="small"
                            value={filters.managedBy ?? 'all'}
                            onChange={(managedBy) => {
                                setFilters({ managedBy })
                                // pinned: analytics event name
                                posthog.capture('transactional emails managed by filter changed', {
                                    managed_by: managedBy,
                                })
                            }}
                            options={[
                                { value: 'all', label: 'All' },
                                { value: 'code', label: 'Code', icon: <IconCode /> },
                                { value: 'posthog', label: 'PostHog', icon: <IconLetter /> },
                            ]}
                            data-attr="transactional-emails-managed-by-filter"
                        />
                    </span>
                    <span className="flex items-center gap-2">
                        <b className="ml-1">Created by</b>
                        <MemberSelect
                            value={filters.createdBy}
                            onChange={(user) => setFilters({ createdBy: user?.id ?? null })}
                        />
                    </span>
                    <span className="flex items-center gap-2">
                        <b className="ml-1">Tags</b>
                        <TagSelect
                            size="small"
                            defaultLabel="Any tags"
                            value={filters.tags}
                            onChange={(tags) => setFilters({ tags })}
                            listDataAttr="transactional-emails-tags-filter-list"
                        />
                    </span>
                </div>
            </div>
            <LemonTable<TransactionalEmailRow>
                dataSource={filteredTransactionalEmails}
                loading={templatesLoading || codeEmailsLoading}
                pagination={{ pageSize: 50, hideOnSinglePage: true }}
                rowKey="id"
                data-attr="transactional-emails-table"
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
                        render: (_, row) => {
                            const sensitive = row.sensitive && (
                                <LemonTag type="highlight" size="small" icon={<IconLock />}>
                                    Sensitive
                                </LemonTag>
                            )
                            if (row.source === 'code') {
                                // The Code tag can link to the source file, so only the key links to the email:
                                // a link can't hold another link.
                                return (
                                    <div className="flex flex-col py-1">
                                        <div className="flex flex-wrap items-center gap-1 font-semibold text-sm">
                                            <Link
                                                subtle
                                                to={urls.transactionalCodeEmail(row.id)}
                                                className="font-mono break-all"
                                                data-attr="transactional-code-email-link"
                                            >
                                                {row.name}
                                            </Link>
                                            <CodeBadge sourceUrl={row.codeEmail.source_url} />
                                            {sensitive}
                                        </div>
                                        {row.description ? (
                                            <div className="text-xs text-tertiary mt-1">{row.description}</div>
                                        ) : null}
                                    </div>
                                )
                            }
                            return (
                                <LemonTableLink
                                    to={urls.transactionalTemplate(row.id)}
                                    title={
                                        <span className="flex flex-wrap items-center gap-1">
                                            {row.name || 'Unnamed template'}
                                            {sensitive}
                                            {row.template.draft_content && (
                                                <LemonTag type="warning" size="small">
                                                    Unpublished changes
                                                </LemonTag>
                                            )}
                                        </span>
                                    }
                                    description={row.description}
                                />
                            )
                        },
                    },
                    {
                        title: 'Tags',
                        key: 'tags',
                        width: 220,
                        isHidden: !wide,
                        render: function Render(_, row) {
                            const shown = {
                                tags: [...row.tags],
                                onTagClick: (tag: string) => {
                                    if (!filters.tags.includes(tag)) {
                                        setFilters({ tags: [...filters.tags, tag] })
                                    }
                                },
                                wrap: true,
                                maxVisibleTags: 2,
                                'data-attr': 'transactional-email-tags',
                            }
                            // An email sent from code follows the reader's access to its own workflow.
                            const tagsDisabledReason =
                                row.source === 'code'
                                    ? getAccessControlDisabledReason(
                                          AccessControlResourceType.Workflow,
                                          AccessControlLevel.Editor,
                                          (row.codeEmail.user_access_level ?? undefined) as
                                              | AccessControlLevel
                                              | undefined
                                      )
                                    : editDisabledReason
                            return tagsDisabledReason ? (
                                <ObjectTags {...shown} staticOnly />
                            ) : (
                                <ObjectTags
                                    {...shown}
                                    onChange={(tags) => saveTransactionalTags(row, tags)}
                                    saving={savingTagsFor === row.id}
                                />
                            )
                        },
                    },
                    {
                        title: 'Last 7 days',
                        width: 0,
                        render: (_, row) => {
                            if (!row.hog_flow_id) {
                                return null
                            }
                            const sparkline = (
                                <AppMetricsSparkline
                                    logicKey={`transactional-${row.id}`}
                                    // Lines, not stacked bars: a delivered or failed email was also counted as sent.
                                    type="line"
                                    metricLabels={{
                                        email_sent: 'Sent',
                                        email_delivered: 'Delivered',
                                        email_failed: 'Failed',
                                    }}
                                    metricColors={{
                                        email_sent: 'blue',
                                        email_delivered: 'success',
                                        email_failed: 'danger',
                                    }}
                                    forceParams={{
                                        appSource: 'hog_flow',
                                        appSourceId: row.hog_flow_id,
                                        metricName: ['email_sent', 'email_delivered', 'email_failed'],
                                        breakdownBy: 'metric_name',
                                        interval: 'day',
                                        dateFrom: '-7d',
                                    }}
                                />
                            )
                            return (
                                <Link
                                    to={
                                        row.source === 'code'
                                            ? urls.transactionalCodeEmail(row.id)
                                            : urls.transactionalTemplate(row.id)
                                    }
                                >
                                    {sparkline}
                                </Link>
                            )
                        },
                    },
                    {
                        ...(createdByColumn() as LemonTableColumn<TransactionalEmailRow, any>),
                        isHidden: !wide,
                        render: (_, row) =>
                            row.source === 'code' ? (
                                <span className="text-secondary whitespace-nowrap">Your code</span>
                            ) : row.created_by ? (
                                <ProfilePicture user={row.created_by} size="md" showName />
                            ) : (
                                <span className="text-secondary">—</span>
                            ),
                    },
                    {
                        ...(updatedAtColumn() as LemonTableColumn<TransactionalEmailRow, any>),
                        width: 0,
                        isHidden: !wide,
                    },
                ]}
                defaultSorting={{ columnKey: 'updated_at', order: -1 }}
                emptyState={isFiltered ? 'No transactional emails match these filters' : 'No transactional emails'}
            />
        </div>
    )
}
