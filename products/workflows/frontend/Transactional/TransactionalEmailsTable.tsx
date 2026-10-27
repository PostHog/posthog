import { useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { IconLock } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { messageTemplatesLogic } from '../TemplateLibrary/messageTemplatesLogic'
import { MessageTemplate } from '../TemplateLibrary/types'

export function TransactionalEmailsTable(): JSX.Element {
    useMountedLogic(messageTemplatesLogic)
    const { transactionalTemplates, templatesLoading } = useValues(messageTemplatesLogic)

    if (!templatesLoading && transactionalTemplates.length === 0) {
        return (
            <ProductIntroduction
                thingName="transactional email"
                description="Send emails from your code with one API call. Use them for emails a person triggers, like password resets, receipts and sign-in codes. This tab shows how many were sent, delivered and failed in the last 7 days."
                docsURL="https://posthog.com/docs/workflows"
                action={() => router.actions.push(urls.transactionalNew())}
                disabledReason={
                    getAccessControlDisabledReason(AccessControlResourceType.Workflow, AccessControlLevel.Editor) ??
                    undefined
                }
                isEmpty
            />
        )
    }

    return (
        <LemonTable<MessageTemplate>
            dataSource={transactionalTemplates}
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
                { ...(updatedAtColumn() as LemonTableColumn<MessageTemplate, any>), width: 0 },
            ]}
            defaultSorting={{ columnKey: 'updated_at', order: -1 }}
            emptyState="No transactional emails match"
        />
    )
}
