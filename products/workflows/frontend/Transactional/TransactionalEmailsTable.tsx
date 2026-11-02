import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconLock } from '@posthog/icons'
import { LemonInput, LemonTag, Link } from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TagSelect } from 'lib/components/TagSelect'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { createdByColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { MessageTemplate } from '../TemplateLibrary/types'
import { transactionalEmailsLogic } from './transactionalEmailsLogic'

export function TransactionalEmailsTable(): JSX.Element {
    const {
        transactionalTemplates,
        filteredTransactionalTemplates,
        templatesLoading,
        filters,
        isFiltered,
        tags: allTags,
        savingTagsFor,
    } = useValues(transactionalEmailsLogic)
    const { setFilters, saveTransactionalTags } = useActions(transactionalEmailsLogic)
    // Same check as the "New transactional email" button: changing a template needs Editor access.
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor
    )

    if (!templatesLoading && transactionalTemplates.length === 0) {
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
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search emails"
                    onChange={(search) => setFilters({ search })}
                    value={filters.search}
                    data-attr="transactional-emails-search"
                />
                <div className="flex flex-wrap items-center gap-2">
                    <b>Created by</b>
                    <MemberSelect
                        value={filters.createdBy}
                        onChange={(user) => setFilters({ createdBy: user?.id ?? null })}
                    />
                    <b className="ml-1">Tags</b>
                    <TagSelect
                        size="small"
                        defaultLabel="Any tags"
                        value={filters.tags}
                        onChange={(tags) => setFilters({ tags })}
                        listDataAttr="transactional-emails-tags-filter-list"
                    />
                </div>
            </div>
            <LemonTable<MessageTemplate>
                dataSource={filteredTransactionalTemplates}
                loading={templatesLoading}
                rowKey="id"
                data-attr="transactional-emails-table"
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
                        render: (_, template) => (
                            <LemonTableLink
                                to={urls.transactionalTemplate(template.id)}
                                title={
                                    <span className="flex items-center gap-1">
                                        {template.name || 'Unnamed template'}
                                        {template.sensitive && (
                                            <LemonTag type="highlight" size="small" icon={<IconLock />}>
                                                Sensitive
                                            </LemonTag>
                                        )}
                                        {template.draft_content && (
                                            <LemonTag type="warning" size="small">
                                                Unpublished changes
                                            </LemonTag>
                                        )}
                                    </span>
                                }
                                description={template.description}
                            />
                        ),
                    },
                    {
                        title: 'Tags',
                        key: 'tags',
                        width: 220,
                        render: function Render(_, template) {
                            const shown = {
                                tags: [...(template.tags ?? [])],
                                onTagClick: (tag: string) => {
                                    if (!filters.tags.includes(tag)) {
                                        setFilters({ tags: [...filters.tags, tag] })
                                    }
                                },
                                wrap: true,
                                maxVisibleTags: 2,
                                'data-attr': 'transactional-email-tags',
                            }
                            return editDisabledReason ? (
                                <ObjectTags {...shown} staticOnly />
                            ) : (
                                <ObjectTags
                                    {...shown}
                                    onChange={(tags) => saveTransactionalTags(template, tags)}
                                    saving={savingTagsFor === template.id}
                                    tagsAvailable={allTags}
                                />
                            )
                        },
                    },
                    {
                        title: 'Last 7 days',
                        width: 0,
                        render: (_, template) =>
                            template.transactional_hog_flow_id ? (
                                <Link to={urls.transactionalTemplate(template.id)}>
                                    <AppMetricsSparkline
                                        logicKey={`transactional-${template.id}`}
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
                                            appSourceId: template.transactional_hog_flow_id,
                                            metricName: ['email_sent', 'email_delivered', 'email_failed'],
                                            breakdownBy: 'metric_name',
                                            interval: 'day',
                                            dateFrom: '-7d',
                                        }}
                                    />
                                </Link>
                            ) : null,
                    },
                    createdByColumn() as LemonTableColumn<MessageTemplate, any>,
                    { ...(updatedAtColumn() as LemonTableColumn<MessageTemplate, any>), width: 0 },
                ]}
                defaultSorting={{ columnKey: 'updated_at', order: -1 }}
                emptyState={isFiltered ? 'No transactional emails match these filters' : 'No transactional emails'}
            />
        </div>
    )
}
