import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardLoadAction } from 'scenes/dashboard/dashboardLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { DashboardPlacement, SidePanelTab } from '~/types'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { DashboardTemplateStatusTag } from './DashboardTemplateStatusTag'
import { GenerationChecks } from './GenerationChecks'
import { metricsDashboardReviewSceneLogic } from './metricsDashboardReviewSceneLogic'

// PostHog AI edits the preview with these tools. The embedded dashboard reloads after each one.
const DASHBOARD_EDIT_TOOLS = [
    'insight-create',
    'insight-update',
    'dashboard-update',
    'dashboard-create-tile',
    'dashboard-delete-tile',
    'dashboard-reorder-tiles',
]

function PreviewDashboard({ dashboardId }: { dashboardId: number }): JSX.Element {
    const { loadDashboard } = useActions(dashboardLogic({ id: dashboardId, placement: DashboardPlacement.Builtin }))
    useMcpToolApplyBack({
        tools: DASHBOARD_EDIT_TOOLS,
        targetKey: `dashboard:${dashboardId}`,
        onApply: () => loadDashboard({ action: DashboardLoadAction.Update }),
    })
    return <Dashboard id={String(dashboardId)} placement={DashboardPlacement.Builtin} />
}

export function DashboardTemplateDetail(): JSX.Element {
    const { template, templateLoading, previewDashboardId, previewDashboardIdLoading, previewError, reviewable } =
        useValues(metricsDashboardReviewSceneLogic)
    const { approveTemplate, rejectTemplate } = useActions(metricsDashboardReviewSceneLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)

    if (!template) {
        return templateLoading ? (
            <LemonSkeleton className="h-64" />
        ) : (
            <LemonBanner type="error">This dashboard does not exist.</LemonBanner>
        )
    }

    const editWithAI = (): void => {
        openSidePanel(
            SidePanelTab.Max,
            `Change the metrics dashboard "${template.name}" (dashboard ${previewDashboardId}): `
        )
    }

    return (
        <>
            <SceneTitleSection
                name={template.name}
                description={template.description}
                resourceType={{ type: 'metrics' }}
                actions={
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconSparkles className="text-ai" />}
                            onClick={editWithAI}
                            disabledReason={
                                !previewDashboardId
                                    ? 'Open the preview first'
                                    : !dataProcessingAccepted
                                      ? (dataProcessingApprovalDisabledReason ??
                                        'Approve AI data processing to use PostHog AI')
                                      : undefined
                            }
                            data-attr="metrics-dashboard-review-edit-with-ai"
                        >
                            <span
                                className={cn(
                                    'rainbow-text font-semibold',
                                    !(inStorybook() || inStorybookTestRunner()) && 'rainbow-text-animating'
                                )}
                            >
                                Edit with PostHog AI
                            </span>
                        </LemonButton>
                        {reviewable && template.status !== 'rejected' && (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                size="small"
                                onClick={rejectTemplate}
                                data-attr="metrics-dashboard-review-reject"
                            >
                                Reject
                            </LemonButton>
                        )}
                        {reviewable && (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={approveTemplate}
                                tooltip="Projects that send these metrics see this dashboard as a suggestion. Your changes to the preview become part of it."
                                data-attr="metrics-dashboard-review-approve"
                            >
                                Approve
                            </LemonButton>
                        )}
                    </>
                }
            />
            <div className="flex flex-wrap items-center gap-2">
                <DashboardTemplateStatusTag template={template} />
                {template.source === 'curated' && <LemonTag type="muted">Curated</LemonTag>}
                {template.reviewed_by && (
                    <span className="text-xs text-secondary">Reviewed by {template.reviewed_by}</span>
                )}
            </div>
            {template.error && <LemonBanner type="error">{template.error}</LemonBanner>}
            <GenerationChecks template={template} />
            {previewDashboardId ? (
                <PreviewDashboard dashboardId={previewDashboardId} />
            ) : previewDashboardIdLoading ? (
                <LemonSkeleton className="h-96" />
            ) : previewError ? (
                <LemonBanner type="info">{previewError}</LemonBanner>
            ) : null}
            <LemonCollapse
                panels={[
                    {
                        key: 'metrics',
                        header: `${template.metric_names.length} metrics`,
                        content: (
                            <div className="@container">
                                <ul className="font-mono text-xs columns-1 @md:columns-2 @2xl:columns-3">
                                    {template.metric_names.map((name) => (
                                        <li key={name} className="truncate">
                                            {name}
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        ),
                    },
                ]}
            />
        </>
    )
}
