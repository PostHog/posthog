import { LemonButton } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { RobotHog } from 'lib/components/hedgehogs'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

export const scene: SceneExport = {
    component: SyntheticUsersScene,
}

export function SyntheticUsersScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.SyntheticUsers].name}
                description={sceneConfigurations[Scene.SyntheticUsers].description}
                resourceType={{
                    type: sceneConfigurations[Scene.SyntheticUsers].iconType ?? 'persons',
                }}
            />
            <ProductIntroduction
                productName="Synthetic users"
                productKey={ProductKey.SYNTHETIC_USERS}
                thingName="synthetic user"
                description={sceneConfigurations[Scene.SyntheticUsers].description ?? ''}
                docsURL="https://posthog.com/docs/synthetic-users"
                customHog={RobotHog}
                isEmpty={true}
                actionElementOverride={
                    <LemonButton type="primary" data-attr="create-synthetic-user">
                        New synthetic user
                    </LemonButton>
                }
            />
        </SceneContent>
    )
}

export default SyntheticUsersScene
