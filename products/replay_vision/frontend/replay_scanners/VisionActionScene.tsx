import { BindLogic, useActions, useValues } from 'kea'

import { IconPencil, IconPlay } from '@posthog/icons'
import { LemonButton, LemonCard, SpinnerOverlay } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { appLogic } from 'scenes/appLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import type { VisionActionApi } from '../generated/api.schemas'
import { VisionActionModeEnumApi } from '../generated/api.schemas'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { humanizeCadence, parseRruleToCadence } from './cadence'
import { VisionActionRuns } from './components/VisionActionRuns'
import { replayScannerLogic } from './replayScannerLogic'
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
    const isAlert = action.mode === VisionActionModeEnumApi.Alert
    const everyMatch = action.alert_config?.frequency === 'every_match'
    // `action.scanner` is only the id — the action's own user_access_level would just reflect the
    // replay_scanner resource default, not a per-scanner object grant, so load the scanner itself.
    const { scanner } = useValues(replayScannerLogic({ id: action.scanner }))
    const { runningNow, runInProgress } = useValues(visionActionRunsLogic)
    const { runNow } = useActions(visionActionRunsLogic)
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner?.user_access_level)

    return (
        <>
            <SceneTitleSection
                name={action.name}
                description={
                    isAlert
                        ? everyMatch
                            ? 'Checked every few minutes; each alert covers the new matches since the last check'
                            : 'Checked about every hour; notifies when the threshold starts being crossed'
                        : scheduleLabel
                          ? // Lowercase only the leading "Daily"/"Weekly" so it reads as a sentence;
                            // keep weekday names and the timezone acronym (e.g. PDT) in their own case.
                            `Runs ${scheduleLabel.charAt(0).toLowerCase()}${scheduleLabel.slice(1)}`
                          : undefined
                }
                resourceType={{ type: 'replay_vision' }}
                actions={
                    <>
                        {!isAlert && (
                            <LemonButton
                                type="secondary"
                                icon={<IconPlay />}
                                onClick={runNow}
                                loading={runningNow}
                                disabledReason={
                                    editDisabledReason ?? (runInProgress ? 'A run is already in progress' : undefined)
                                }
                                data-attr="vision-action-run-now"
                            >
                                {runInProgress ? 'Running…' : 'Run now'}
                            </LemonButton>
                        )}
                        <LemonButton
                            type="secondary"
                            icon={<IconPencil />}
                            to={urls.replayVisionActionEdit(action.id)}
                            disabledReason={editDisabledReason}
                            data-attr="vision-action-edit-from-page"
                        >
                            Edit
                        </LemonButton>
                    </>
                }
            />
            {!isAlert && (
                <LemonCard hoverEffect={false} className="p-4">
                    <div className="text-xs font-semibold uppercase text-secondary mb-1">Digest guidance</div>
                    {guidance ? (
                        <p className="m-0 whitespace-pre-wrap">{guidance}</p>
                    ) : (
                        <p className="m-0 text-muted italic">
                            No guidance set — the AI summarizes this scanner's observations freely. Edit the action to
                            steer it.
                        </p>
                    )}
                </LemonCard>
            )}
        </>
    )
}

function VisionActionDetail(): JSX.Element {
    const { action, actionLoading } = useValues(visionActionRunsLogic)
    const rrule = action?.trigger_config?.rrule
    const schedule = rrule ? humanizeCadence(parseRruleToCadence(rrule), action?.trigger_config?.timezone) : null

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
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)
    const { featureFlagsTimedOut } = useValues(appLogic)

    if (!featureFlags[FEATURE_FLAGS.REPLAY_VISION] || !featureFlags[FEATURE_FLAGS.REPLAY_VISION_ACTIONS]) {
        // Flags load asynchronously, so wait for them before deciding the page doesn't exist.
        if (!receivedFeatureFlags && !featureFlagsTimedOut) {
            return <SpinnerOverlay sceneLevel />
        }
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
