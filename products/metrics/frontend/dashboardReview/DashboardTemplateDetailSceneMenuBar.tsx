import { useActions, useValues } from 'kea'

import { IconCheck, IconRefresh, IconSparkles, IconX } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook } from 'lib/utils/dom'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import type { MetricsDashboardTemplateApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsDashboardReviewSceneLogic } from './metricsDashboardReviewSceneLogic'

const RESOURCE_TYPE = 'metrics-dashboard-review'

const APPROVE_TOOLTIP =
    'Projects that send these metrics see this dashboard as a suggestion. Your changes to the preview become part of it.'

interface DashboardTemplateDetailSceneMenuBarProps {
    template: MetricsDashboardTemplateApi
    onEditWithAI: () => void
}

export function DashboardTemplateDetailSceneMenuBar(
    props: DashboardTemplateDetailSceneMenuBarProps
): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <DashboardTemplateDetailSceneMenuBarInner {...props} /> : null
}

function DashboardTemplateDetailSceneMenuBarInner({
    template,
    onEditWithAI,
}: DashboardTemplateDetailSceneMenuBarProps): JSX.Element {
    const { templateLoading, previewDashboardId, reviewable, regenerable } = useValues(metricsDashboardReviewSceneLogic)
    const { approveTemplate, rejectTemplate, confirmRegenerate } = useActions(metricsDashboardReviewSceneLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const savingReason = templateLoading ? 'Saving the dashboard' : undefined
    const editWithAIDisabledReason = !reviewable
        ? 'Only a dashboard that waits for review can be changed'
        : !previewDashboardId
          ? 'Open the preview first'
          : !dataProcessingAccepted
            ? (dataProcessingApprovalDisabledReason ?? 'Approve AI data processing to use PostHog AI')
            : undefined

    const actions: SceneAction[] = [
        {
            group: 'edit',
            section: 'ai',
            id: `${RESOURCE_TYPE}-menubar-edit-with-ai`,
            label: 'Edit with PostHog AI',
            icon: <IconSparkles className="text-ai" />,
            opensFloatingUi: true,
            disabledReason: editWithAIDisabledReason,
            onSelect: onEditWithAI,
            pinned: {
                order: 1,
                variant: 'secondary',
                render: () => (
                    <Button
                        variant="outline"
                        onClick={onEditWithAI}
                        disabledReason={editWithAIDisabledReason}
                        data-attr="metrics-dashboard-review-edit-with-ai"
                    >
                        <IconSparkles className="text-ai" />
                        <span className={cn('rainbow-text font-semibold', !inStorybook() && 'rainbow-text-animating')}>
                            Edit with PostHog AI
                        </span>
                    </Button>
                ),
            },
        },
        ...(regenerable
            ? ([
                  {
                      group: 'edit',
                      section: 'review',
                      id: `${RESOURCE_TYPE}-menubar-regenerate`,
                      label: 'Regenerate',
                      icon: <IconRefresh />,
                      opensFloatingUi: true,
                      disabledReason: savingReason,
                      onSelect: confirmRegenerate,
                  },
              ] satisfies SceneAction[])
            : []),
        ...(reviewable && template.status !== 'rejected'
            ? ([
                  {
                      group: 'edit',
                      section: 'review',
                      id: `${RESOURCE_TYPE}-menubar-reject`,
                      label: 'Reject',
                      icon: <IconX />,
                      disabledReason: savingReason,
                      onSelect: rejectTemplate,
                      pinned: {
                          order: 2,
                          variant: 'secondary',
                          render: () => (
                              <Button
                                  variant="destructive-outline"
                                  onClick={rejectTemplate}
                                  loading={templateLoading}
                                  data-attr="metrics-dashboard-review-reject"
                              >
                                  Reject
                              </Button>
                          ),
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(reviewable
            ? ([
                  {
                      group: 'edit',
                      section: 'review',
                      id: `${RESOURCE_TYPE}-menubar-approve`,
                      label: 'Approve',
                      icon: <IconCheck />,
                      tooltip: APPROVE_TOOLTIP,
                      disabledReason: savingReason,
                      onSelect: approveTemplate,
                      pinned: {
                          order: 3,
                          variant: 'primary',
                          render: () => (
                              <Button
                                  variant="primary"
                                  onClick={approveTemplate}
                                  loading={templateLoading}
                                  tooltip={APPROVE_TOOLTIP}
                                  data-attr="metrics-dashboard-review-approve"
                              >
                                  Approve
                              </Button>
                          ),
                      },
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
