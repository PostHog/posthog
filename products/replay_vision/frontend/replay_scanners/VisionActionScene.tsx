import { BindLogic, useValues } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { humanizeCadence, parseRruleToCadence } from './cadence'
import { VisionActionRuns } from './components/VisionActionRuns'
import { visionActionRunsLogic } from './visionActionRunsLogic'
import { visionActionSceneLogic } from './visionActionSceneLogic'

export const scene: SceneExport = {
    component: VisionActionSceneComponent,
    logic: visionActionSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

function VisionActionDetail(): JSX.Element {
    const { action, actionLoading } = useValues(visionActionRunsLogic)

    const title = action?.name ?? (actionLoading ? 'Loading…' : 'Action runs')
    const rrule = action?.trigger_config?.rrule
    const schedule = rrule ? humanizeCadence(parseRruleToCadence(rrule)) : null

    return (
        <SceneContent>
            <SceneTitleSection
                name={title}
                description={schedule ? `Runs ${schedule.toLowerCase()}` : undefined}
                resourceType={{ type: 'replay_vision' }}
            />
            <VisionActionRuns />
        </SceneContent>
    )
}

function VisionActionSceneComponent(): JSX.Element {
    const { actionId } = useValues(visionActionSceneLogic)

    if (!actionId) {
        return (
            <SceneContent>
                <SceneTitleSection name="Loading…" resourceType={{ type: 'replay_vision' }} />
            </SceneContent>
        )
    }

    return (
        <BindLogic logic={visionActionRunsLogic} props={{ actionId }}>
            <VisionActionDetail />
        </BindLogic>
    )
}
