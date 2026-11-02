import { useValues } from 'kea'

import { AccessDenied } from 'lib/components/AccessDenied'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { DashboardTemplateDetail } from './DashboardTemplateDetail'
import { DashboardTemplateList } from './DashboardTemplateList'
import { metricsDashboardReviewSceneLogic } from './metricsDashboardReviewSceneLogic'

export const scene: SceneExport = {
    component: MetricsDashboardReviewScene,
    logic: metricsDashboardReviewSceneLogic,
}

export function MetricsDashboardReviewScene(): JSX.Element {
    const { user } = useValues(userLogic)
    const { templateId } = useValues(metricsDashboardReviewSceneLogic)

    if (!user?.is_staff) {
        return <AccessDenied object="page" reason="This page is only accessible to staff users." />
    }

    return <SceneContent>{templateId ? <DashboardTemplateDetail /> : <DashboardTemplateList />}</SceneContent>
}
