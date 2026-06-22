import { BindLogic, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

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

function VisionActionSceneComponent(): JSX.Element {
    const { action, actionLoading } = useValues(visionActionSceneLogic)

    if (actionLoading && !action) {
        return (
            <SceneContent>
                <SceneTitleSection name="Loading…" resourceType={{ type: 'replay_vision' }} />
            </SceneContent>
        )
    }

    if (!action) {
        return (
            <SceneContent>
                <SceneTitleSection name="Action not found" resourceType={{ type: 'replay_vision' }} />
                <p className="text-muted">
                    This action either doesn't exist or you don't have access to it.{' '}
                    <Link to={urls.replayVision()}>Back to scanners</Link>.
                </p>
            </SceneContent>
        )
    }

    const rrule = action.trigger_config?.rrule
    const schedule = rrule ? humanizeCadence(parseRruleToCadence(rrule)) : null

    return (
        <SceneContent>
            <SceneTitleSection
                name={action.name}
                description={schedule ? `Runs ${schedule.toLowerCase()}` : undefined}
                resourceType={{ type: 'replay_vision' }}
            />
            <BindLogic logic={visionActionRunsLogic} props={{ actionId: action.id }}>
                <VisionActionRuns />
            </BindLogic>
        </SceneContent>
    )
}
