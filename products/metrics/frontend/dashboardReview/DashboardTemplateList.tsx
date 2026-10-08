import { useActions, useValues } from 'kea'

import { LemonButton, LemonSegmentedButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { MetricsDashboardTemplateApi } from 'products/metrics/frontend/generated/api.schemas'

import { DashboardTemplateStatusTag } from './DashboardTemplateStatusTag'
import { ReviewStatusFilter, metricsDashboardReviewSceneLogic } from './metricsDashboardReviewSceneLogic'

const STATUS_OPTIONS: { value: ReviewStatusFilter; label: string }[] = [
    { value: 'pending_review', label: 'Pending review' },
    { value: 'approved', label: 'Approved' },
    { value: 'rejected', label: 'Rejected' },
    { value: 'all', label: 'All' },
]

export function DashboardTemplateList(): JSX.Element {
    const { templates, templatesLoading, statusFilter } = useValues(metricsDashboardReviewSceneLogic)
    const { setStatusFilter, analyzeProject } = useActions(metricsDashboardReviewSceneLogic)

    return (
        <>
            <SceneTitleSection
                name="Dashboard review"
                description="Approve AI-generated metrics dashboards before projects see them."
                resourceType={{ type: 'metrics' }}
                actions={
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={analyzeProject}
                        tooltip="Look for new groups of metrics in this project, and generate dashboards for them."
                        data-attr="metrics-dashboard-review-analyze"
                    >
                        Analyze this project
                    </LemonButton>
                }
            />
            <LemonSegmentedButton
                size="small"
                value={statusFilter}
                onChange={setStatusFilter}
                options={STATUS_OPTIONS}
                data-attr="metrics-dashboard-review-status"
            />
            <LemonTable<MetricsDashboardTemplateApi>
                dataSource={templates ?? []}
                loading={templatesLoading}
                rowKey="id"
                emptyState="No dashboards here."
                columns={[
                    {
                        title: 'Dashboard',
                        key: 'name',
                        render: (_, template) => (
                            <LemonTableLink
                                to={urls.metricsDashboardReview(template.id)}
                                title={
                                    <span className="flex items-center gap-2">
                                        {template.name}
                                        {template.source === 'curated' && <LemonTag type="muted">Curated</LemonTag>}
                                    </span>
                                }
                                description={template.description}
                            />
                        ),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, template) => <DashboardTemplateStatusTag template={template} />,
                    },
                    {
                        title: 'Charts',
                        key: 'charts',
                        align: 'right',
                        render: (_, template) => template.panel_titles.length,
                    },
                    ...(statusFilter === 'approved' || statusFilter === 'all'
                        ? [
                              {
                                  title: 'Projects',
                                  key: 'suggestions',
                                  align: 'right' as const,
                                  tooltip: 'Projects that see this dashboard as a suggestion.',
                                  render: (_: unknown, template: MetricsDashboardTemplateApi) =>
                                      template.suggestion_count,
                              },
                          ]
                        : []),
                    {
                        title: 'Created',
                        key: 'created_at',
                        render: (_, template) => <TZLabel time={template.created_at} />,
                    },
                ]}
            />
        </>
    )
}
