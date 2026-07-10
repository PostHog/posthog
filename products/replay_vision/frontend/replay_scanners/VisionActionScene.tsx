import { BindLogic, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { VisionActionApi } from '../generated/api.schemas'
import { humanizeCadence, parseRruleToCadence } from './cadence'
import { VisionActionRuns } from './components/VisionActionRuns'
import { visionActionRunsLogic } from './visionActionRunsLogic'
import { visionActionSceneLogic } from './visionActionSceneLogic'

export const scene: SceneExport = {
    component: VisionActionSceneComponent,
    logic: visionActionSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

// The title bar and current-guidance panel, shown once the action loads. Edit links to the action
// editor page.
function ActionOverview({
    action,
    scheduleLabel,
}: {
    action: VisionActionApi
    scheduleLabel: string | null
}): JSX.Element {
    const guidance = action.synthesis_config?.prompt_guide?.trim()

    return (
        <>
            <SceneTitleSection
                name={action.name}
                description={scheduleLabel ? `Runs ${scheduleLabel.toLowerCase()}` : undefined}
                resourceType={{ type: 'replay_vision' }}
                actions={
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="secondary"
                            icon={<IconPencil />}
                            to={urls.replayVisionActionEdit(action.id)}
                            data-attr="vision-action-edit-from-page"
                        >
                            Edit
                        </LemonButton>
                    </AccessControlAction>
                }
            />
            <LemonCard hoverEffect={false} className="p-4">
                <div className="text-xs font-semibold uppercase text-secondary mb-1">Summary guidance</div>
                {guidance ? (
                    <p className="m-0 whitespace-pre-wrap">{guidance}</p>
                ) : (
                    <p className="m-0 text-muted italic">
                        No guidance set — the AI summarizes this scanner's observations freely. Edit the action to steer
                        it.
                    </p>
                )}
            </LemonCard>
        </>
    )
}

function VisionActionDetail(): JSX.Element {
    const { action, actionLoading } = useValues(visionActionRunsLogic)
    const rrule = action?.trigger_config?.rrule
    const schedule = rrule ? humanizeCadence(parseRruleToCadence(rrule)) : null

    return (
        <SceneContent>
            {action ? (
                <ActionOverview action={action} scheduleLabel={schedule} />
            ) : (
                <SceneTitleSection
                    name={actionLoading ? 'Loading…' : 'Action runs'}
                    resourceType={{ type: 'replay_vision' }}
                />
            )}
            <VisionActionRuns />
        </SceneContent>
    )
}

function VisionActionSceneComponent(): JSX.Element {
    const { actionId } = useValues(visionActionSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.REPLAY_VISION] || !featureFlags[FEATURE_FLAGS.REPLAY_VISION_ACTIONS]) {
        return <NotFound object="page" />
    }

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
