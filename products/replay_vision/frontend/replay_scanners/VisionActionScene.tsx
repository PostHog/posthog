import { BindLogic, useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { VisionActionApi } from '../generated/api.schemas'
import { humanizeCadence, parseRruleToCadence } from './cadence'
import { VisionActionForm } from './components/VisionActionForm'
import { VisionActionRuns } from './components/VisionActionRuns'
import { visionActionRunsLogic } from './visionActionRunsLogic'
import { visionActionSceneLogic } from './visionActionSceneLogic'
import { visionActionsLogic } from './visionActionsLogic'

export const scene: SceneExport = {
    component: VisionActionSceneComponent,
    logic: visionActionSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

// The title bar, current-guidance panel, and edit modal — shown once the action loads. Bound to
// visionActionsLogic (keyed by the scanner) so the shared create/edit form drives the modal here too.
function ActionOverview({
    action,
    scheduleLabel,
}: {
    action: VisionActionApi
    scheduleLabel: string | null
}): JSX.Element {
    const { openEditForm } = useActions(visionActionsLogic)
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
                            onClick={() => openEditForm(action)}
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
            <VisionActionForm scannerId={action.scanner} />
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
                <BindLogic logic={visionActionsLogic} props={{ scannerId: action.scanner }}>
                    <ActionOverview action={action} scheduleLabel={schedule} />
                </BindLogic>
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
