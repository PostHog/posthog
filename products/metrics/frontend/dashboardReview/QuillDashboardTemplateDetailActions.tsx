import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import type { MetricsDashboardTemplateApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsDashboardReviewSceneLogic } from './metricsDashboardReviewSceneLogic'

export interface QuillDashboardTemplateDetailActionsProps {
    template: MetricsDashboardTemplateApi
    onEditWithAI: () => void
}

export function QuillDashboardTemplateDetailActions({
    template,
    onEditWithAI,
}: QuillDashboardTemplateDetailActionsProps): JSX.Element {
    const { templateLoading, previewDashboardId, reviewable, regenerable } = useValues(metricsDashboardReviewSceneLogic)
    const { approveTemplate, rejectTemplate, confirmRegenerate } = useActions(metricsDashboardReviewSceneLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <Button
                variant="outline"
                onClick={onEditWithAI}
                disabledReason={
                    !reviewable
                        ? 'Only a dashboard that waits for review can be changed'
                        : !previewDashboardId
                          ? 'Open the preview first'
                          : !dataProcessingAccepted
                            ? (dataProcessingApprovalDisabledReason ?? 'Approve AI data processing to use PostHog AI')
                            : undefined
                }
                data-attr="metrics-dashboard-review-edit-with-ai"
            >
                <IconSparkles className="text-ai" />
                <span
                    className={cn(
                        'rainbow-text font-semibold',
                        !(inStorybook() || inStorybookTestRunner()) && 'rainbow-text-animating'
                    )}
                >
                    Edit with PostHog AI
                </span>
            </Button>
            {regenerable && (
                <Button
                    variant="outline"
                    onClick={confirmRegenerate}
                    loading={templateLoading}
                    data-attr="metrics-dashboard-review-regenerate"
                >
                    Regenerate
                </Button>
            )}
            {reviewable && template.status !== 'rejected' && (
                <Button
                    variant="destructive-outline"
                    onClick={rejectTemplate}
                    loading={templateLoading}
                    data-attr="metrics-dashboard-review-reject"
                >
                    Reject
                </Button>
            )}
            {reviewable && (
                <Button
                    variant="primary"
                    onClick={approveTemplate}
                    loading={templateLoading}
                    tooltip="Projects that send these metrics see this dashboard as a suggestion. Your changes to the preview become part of it."
                    data-attr="metrics-dashboard-review-approve"
                >
                    Approve
                </Button>
            )}
        </div>
    )
}
