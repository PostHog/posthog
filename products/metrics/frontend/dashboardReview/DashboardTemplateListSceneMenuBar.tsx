import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { metricsDashboardReviewSceneLogic } from './metricsDashboardReviewSceneLogic'

const RESOURCE_TYPE = 'metrics-dashboard-review'

const ANALYZE_TOOLTIP = 'Look for new groups of metrics in this project, and generate dashboards for them.'

export function DashboardTemplateListSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <DashboardTemplateListSceneMenuBarInner /> : null
}

function DashboardTemplateListSceneMenuBarInner(): JSX.Element {
    const { analysisStartedLoading } = useValues(metricsDashboardReviewSceneLogic)
    const { analyzeProject } = useActions(metricsDashboardReviewSceneLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-analyze`,
            label: 'Analyze this project',
            icon: <IconSparkles />,
            tooltip: ANALYZE_TOOLTIP,
            disabledReason: analysisStartedLoading ? 'Starting the analysis' : undefined,
            onSelect: analyzeProject,
            pinned: {
                order: 1,
                variant: 'secondary',
                render: () => (
                    <Button
                        variant="outline"
                        onClick={analyzeProject}
                        loading={analysisStartedLoading}
                        tooltip={ANALYZE_TOOLTIP}
                        data-attr="metrics-dashboard-review-analyze"
                    >
                        Analyze this project
                    </Button>
                ),
            },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
