import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    TabsPrimitive,
    TabsPrimitiveContent,
    TabsPrimitiveList,
    TabsPrimitiveTrigger,
} from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ErrorTrackingSetupPrompt } from './components/ErrorTrackingSetupPrompt/ErrorTrackingSetupPrompt'
import { ErrorTrackingIssueFilteringTool } from './components/IssueFilteringTool'
import { ErrorTrackingIssueImpactTool } from './components/IssueImpactTool'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'
import { ErrorTrackingImpactList } from './scenes/ErrorTrackingScene/tabs/impact/ErrorTrackingImpactList'
import { ErrorTrackingIssuesList } from './scenes/ErrorTrackingScene/tabs/issues/ErrorTrackingIssuesList'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <ErrorTrackingSetupPrompt>
            <ErrorTrackingIssueFilteringTool />
            {featureFlags[FEATURE_FLAGS.ERROR_TRACKING_IMPACT_MAX_TOOL] && <ErrorTrackingIssueImpactTool />}
            <SceneContent>
                <TabsPrimitive defaultValue="issues">
                    <TabsPrimitiveList>
                        <TabsPrimitiveTrigger value="issues">Issues</TabsPrimitiveTrigger>
                        <TabsPrimitiveTrigger value="impact">Impact</TabsPrimitiveTrigger>
                    </TabsPrimitiveList>
                    <TabsPrimitiveContent value="issues">
                        <ErrorTrackingIssuesList />
                    </TabsPrimitiveContent>
                    <TabsPrimitiveContent value="impact">
                        <ErrorTrackingImpactList />
                    </TabsPrimitiveContent>
                </TabsPrimitive>
            </SceneContent>
        </ErrorTrackingSetupPrompt>
    )
}
