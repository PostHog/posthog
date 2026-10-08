import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { EmailSuspensionBanner } from '../EmailSuspensionBanner'
import { NewCategoryButton } from '../OptOuts/NewCategoryButton'
import { OptOutScene } from '../OptOuts/OptOutScene'
import { SuppressionScene } from '../Suppression/SuppressionScene'
import { AUDIENCE_TAB_LABELS, AudienceTab, audienceSceneLogic } from './audienceSceneLogic'

export const scene: SceneExport = {
    component: AudienceScene,
    logic: audienceSceneLogic,
    productKey: ProductKey.WORKFLOWS,
}

const AUDIENCE_SCENE_TABS: LemonTab<AudienceTab>[] = [
    {
        key: 'topics',
        label: AUDIENCE_TAB_LABELS.topics,
        link: urls.audience('topics'),
        content: <OptOutScene />,
    },
    {
        key: 'suppression',
        label: AUDIENCE_TAB_LABELS.suppression,
        link: urls.audience('suppression'),
        content: <SuppressionScene />,
    },
]

export function AudienceScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTab } = useValues(audienceSceneLogic)

    if (!featureFlags[FEATURE_FLAGS.WORKFLOWS_AUDIENCE]) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Audience].name}
                description={sceneConfigurations[Scene.Audience].description}
                resourceType={{ type: 'cohort' }}
                actions={currentTab === 'topics' ? <NewCategoryButton /> : undefined}
            />
            <EmailSuspensionBanner />
            <LemonTabs activeKey={currentTab} tabs={AUDIENCE_SCENE_TABS} sceneInset data-attr="audience-scene-tabs" />
        </SceneContent>
    )
}
