import { BindLogic, useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconPencil, IconPlay } from '@posthog/icons'
import { LemonButton, LemonCard, SpinnerOverlay } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { slackChannelDisplayName } from 'lib/integrations/slackChannel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { appLogic } from 'scenes/appLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import type { VisionActionApi } from '../generated/api.schemas'
import { DeliveryTargetTypeEnumApi, VisionActionModeEnumApi } from '../generated/api.schemas'
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

function ConfigRow({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col sm:flex-row sm:gap-4">
            <div className="text-xs font-semibold uppercase text-secondary sm:w-32 sm:shrink-0 sm:pt-0.5">{label}</div>
            <div className="flex-1 min-w-0">{children}</div>
        </div>
    )
}

function deliveryRow(action: VisionActionApi, noun: string): JSX.Element {
    const target = action.delivery_config?.[0]
    if (target?.type === DeliveryTargetTypeEnumApi.Webhook) {
        return (
            <p className="m-0">
                Webhook at <span className="font-mono text-sm break-all">{target.url}</span>
            </p>
        )
    }
    if (target?.type === DeliveryTargetTypeEnumApi.Slack) {
        return <p className="m-0">Slack in {slackChannelDisplayName(target.channel ?? '') || 'a channel'}</p>
    }
    return (
        <p className="m-0 text-muted italic">
            Not sent anywhere. Edit the action to deliver this {noun} to Slack or a webhook.
        </p>
    )
}

// One card summarizing the action's config — schedule, guidance (digests), and delivery — so it's all
// visible without opening the editor.
function ConfigCard({
    action,
    scheduleLabel,
    noun,
}: {
    action: VisionActionApi
    scheduleLabel: string | null
    noun: string
}): JSX.Element {
    const isAlert = action.mode === VisionActionModeEnumApi.Alert
    const guidance = action.synthesis_config?.prompt_guide?.trim()

    return (
        <LemonCard hoverEffect={false} className="p-4">
            <div className="flex flex-col gap-3">
                <ConfigRow label={isAlert ? 'Checks' : 'Schedule'}>
                    <p className="m-0">
                        {isAlert
                            ? action.alert_config?.frequency === 'every_match'
                                ? 'Every few minutes; each alert covers the new matches since the last check'
                                : 'About every hour; notifies when the threshold starts being crossed'
                            : scheduleLabel || 'Not scheduled'}
                    </p>
                </ConfigRow>
                {!isAlert && (
                    <ConfigRow label="Guidance">
                        {guidance ? (
                            <p className="m-0 whitespace-pre-wrap">{guidance}</p>
                        ) : (
                            <p className="m-0 text-muted italic">
                                None set. The AI summarizes this scanner's observations freely.
                            </p>
                        )}
                    </ConfigRow>
                )}
                <ConfigRow label="Delivery">{deliveryRow(action, noun)}</ConfigRow>
            </div>
        </LemonCard>
    )
}

// The title bar and config summary, shown once the action loads. Edit links to the action editor page.
function ActionOverview({
    action,
    scheduleLabel,
}: {
    action: VisionActionApi
    scheduleLabel: string | null
}): JSX.Element {
    const isAlert = action.mode === VisionActionModeEnumApi.Alert
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
            <ConfigCard action={action} scheduleLabel={scheduleLabel} noun={isAlert ? 'alert' : 'digest'} />
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
