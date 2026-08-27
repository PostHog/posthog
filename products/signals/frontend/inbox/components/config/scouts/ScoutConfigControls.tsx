import { useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonSelect, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import type {
    PatchedSignalScoutConfigUpdateApi as SignalScoutConfigUpdate,
    SignalScoutConfigApi as SignalScoutConfig,
} from 'products/signals/frontend/generated/api.schemas'
import { ScoutConfigNetworkAccessEnumApi } from 'products/signals/frontend/generated/api.schemas'

import {
    dailyCronToTime,
    DEFAULT_SCOUT_DAILY_TIME,
    getScoutScheduleMode,
    getScoutScheduleOptions,
    prettifyScoutSkillName,
    SCOUT_CUSTOM_CRON_SCHEDULE_MODE,
    SCOUT_DAILY_AT_SCHEDULE_MODE,
    timeToDailyCron,
} from '../../../utils/scoutRunsWindow'
import { ScoutMcpServersPicker } from './ScoutMcpServersPicker'
import { ScoutSlackDestination } from './ScoutSlackDestination'
import { ScoutTagsEditor } from './ScoutTagsEditor'

interface ScoutConfigControlsProps {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    updating?: boolean
}

interface ScoutConfigFormProps extends ScoutConfigControlsProps {
    onDelete?: (configId: string) => void
    /** True while this scout's delete request is in flight — disables the delete button. */
    deleting?: boolean
    /** True while this scout's config update request is in flight. */
    updating?: boolean
}

/** Enable/disable toggle for a scout. Lives on the row, not in the settings form. */
export function ScoutEnabledSwitch({ config, onUpdate, updating = false }: ScoutConfigControlsProps): JSX.Element {
    return (
        <Tooltip title={config.enabled ? 'Disable scout' : 'Enable scout'}>
            <span>
                <LemonSwitch
                    size="small"
                    checked={config.enabled}
                    onChange={(checked) => onUpdate(config.id, { enabled: checked })}
                    loading={updating}
                    disabledReason={updating ? 'Saving scout settings' : undefined}
                    aria-label={`${config.skill_name} enabled`}
                />
            </span>
        </Tooltip>
    )
}

/**
 * Labeled settings form for one scout, shown when a fleet row's gear is toggled
 * open. Everything except enablement, which stays on the row.
 */
export function ScoutConfigForm({
    config,
    onUpdate,
    onDelete,
    deleting,
    updating = false,
}: ScoutConfigFormProps): JSX.Element {
    const { timezone: projectTimezone } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const dailyTime = dailyCronToTime(config.run_cron_schedule)
    const scheduleMode = getScoutScheduleMode(config)
    const controlsDisabledReason = updating
        ? 'Saving scout settings'
        : config.enabled
          ? undefined
          : 'Enable the scout first'

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-4">
                <div className="flex flex-col min-w-0">
                    <span className="text-xs text-default">Write signals to the inbox</span>
                    <span className="text-[11.5px] text-muted">
                        Turn this off for a dry run. The scout still runs on its schedule, and its signals stay out of
                        the inbox.
                    </span>
                </div>
                <LemonSwitch
                    size="small"
                    checked={config.emit}
                    // Editable while the scout is disabled, like network access: a newly enabled
                    // scout with no prior run is immediately due, so the dry-run posture must be
                    // settable BEFORE the enable or the first run reaches the inbox anyway.
                    disabledReason={updating ? 'Saving scout settings' : undefined}
                    onChange={(checked) => onUpdate(config.id, { emit: checked })}
                    aria-label={`${config.skill_name} write signals to the inbox`}
                />
            </div>
            <div className="flex items-center justify-between gap-4">
                <div className="flex flex-col min-w-0">
                    <span className="text-xs text-default">Schedule</span>
                    <span className="text-[11.5px] text-muted">
                        {scheduleMode === SCOUT_CUSTOM_CRON_SCHEDULE_MODE
                            ? 'A cron schedule set via the API'
                            : 'A rolling cadence, or a set time each day'}
                    </span>
                </div>
                <LemonSelect
                    size="small"
                    value={scheduleMode}
                    options={getScoutScheduleOptions(config)}
                    disabledReason={controlsDisabledReason}
                    className="w-44"
                    onChange={(value) => {
                        if (value === scheduleMode || value === SCOUT_CUSTOM_CRON_SCHEDULE_MODE) {
                            return
                        }
                        if (value === SCOUT_DAILY_AT_SCHEDULE_MODE) {
                            onUpdate(config.id, {
                                run_cron_schedule: timeToDailyCron(dailyTime ?? DEFAULT_SCOUT_DAILY_TIME),
                            })
                            return
                        }
                        // A rolling cadence replaces any cron — the schedule is one or the other.
                        onUpdate(config.id, { run_interval_minutes: Number(value), run_cron_schedule: null })
                    }}
                />
            </div>
            {scheduleMode === SCOUT_DAILY_AT_SCHEDULE_MODE ? (
                <div className="flex items-center justify-between gap-4">
                    <div className="flex flex-col min-w-0">
                        <span className="text-xs text-default">Run time</span>
                        <span className="text-[11.5px] text-muted">Uses the project timezone ({projectTimezone})</span>
                    </div>
                    <LemonInput
                        key={config.run_cron_schedule ?? 'unset'}
                        type="time"
                        step={60}
                        size="small"
                        defaultValue={dailyTime ?? DEFAULT_SCOUT_DAILY_TIME}
                        disabledReason={controlsDisabledReason}
                        className="w-44"
                        onBlur={(event) => {
                            const value = event.currentTarget.value
                            // Empty means a half-finished edit, never "clear" — turning the
                            // schedule off is the select's job, so just fall back to the saved time.
                            if (!value) {
                                return
                            }
                            const runCronSchedule = timeToDailyCron(value)
                            if (runCronSchedule !== config.run_cron_schedule) {
                                onUpdate(config.id, { run_cron_schedule: runCronSchedule })
                            }
                        }}
                    />
                </div>
            ) : null}
            <div className="flex items-center justify-between gap-4">
                <div className="flex flex-col min-w-0">
                    <span className="text-xs text-default">Network access</span>
                    <span className="text-[11.5px] text-muted">
                        What the scout can reach while it runs. Trusted domains cover PostHog, GitHub, and common
                        package registries. Full access lets it reach any site.
                    </span>
                </div>
                <LemonSelect
                    size="small"
                    value={config.network_access}
                    options={[
                        { value: ScoutConfigNetworkAccessEnumApi.Trusted, label: 'Trusted domains only' },
                        { value: ScoutConfigNetworkAccessEnumApi.Full, label: 'Full access' },
                    ]}
                    // Editable while the scout is disabled, unlike the schedule controls: a newly
                    // enabled scout with no prior run is immediately due, so network access must be
                    // settable BEFORE the enable or the first run races out under the default policy.
                    disabledReason={updating ? 'Saving scout settings' : undefined}
                    className="w-44"
                    onChange={(value) => {
                        if (value !== config.network_access) {
                            onUpdate(config.id, { network_access: value })
                        }
                    }}
                />
            </div>
            {featureFlags[FEATURE_FLAGS.SCOUTS_MODEL_CONFIG] ? (
                <div className="flex items-center justify-between gap-4">
                    <div className="flex flex-col min-w-0">
                        <span className="text-xs text-default">Model</span>
                        <span className="text-[11.5px] text-muted">
                            The model this scout runs on. Pick a more capable model for harder tasks. Leave empty to use
                            the default.
                        </span>
                    </div>
                    <LemonInput
                        key={config.model ?? 'unset'}
                        size="small"
                        placeholder="Default"
                        defaultValue={config.model ?? ''}
                        // Editable while the scout is disabled for the same reason as network access:
                        // a newly enabled scout is immediately due, so the model must be settable first.
                        disabledReason={updating ? 'Saving scout settings' : undefined}
                        className="w-44"
                        onBlur={(event) => {
                            const value = event.currentTarget.value.trim()
                            if (value !== (config.model ?? '')) {
                                onUpdate(config.id, { model: value || null })
                            }
                        }}
                        aria-label={`${config.skill_name} model`}
                    />
                </div>
            ) : null}
            <div className="flex items-center justify-between gap-4">
                <div className="flex flex-col min-w-0">
                    <span className="text-xs text-default">Opt out of auto-pause</span>
                    <span className="text-[11.5px] text-muted">
                        A scout is paused when nobody acts on its reports for a few weeks, and flagged as quiet when it
                        surfaces nothing. Turn this on to opt this scout out of both.
                    </span>
                </div>
                <LemonSwitch
                    size="small"
                    checked={config.auto_pause_exempt}
                    disabledReason={controlsDisabledReason}
                    onChange={(checked) => onUpdate(config.id, { auto_pause_exempt: checked })}
                    aria-label={`${config.skill_name} opt out of auto-pause`}
                />
            </div>
            <div className="flex flex-col gap-1">
                <div className="flex flex-col min-w-0">
                    <span className="text-xs text-default">Tags</span>
                    <span className="text-[11.5px] text-muted">Use tags to group scouts and filter the list.</span>
                </div>
                <ScoutTagsEditor config={config} onUpdate={onUpdate} updating={updating} />
            </div>
            <ScoutSlackDestination
                destination={config.output_destinations?.slack}
                onChange={(outputDestinations) => onUpdate(config.id, { output_destinations: outputDestinations })}
                disabledReason={controlsDisabledReason}
            />
            <ScoutMcpServersPicker
                compact
                selectedServerIds={[...(config.mcp_gateway_server_ids ?? [])]}
                onChange={(serverIds) => onUpdate(config.id, { mcp_gateway_server_ids: serverIds })}
                // Editable while the scout is disabled, like network access: the selection must be
                // settable BEFORE the enable or the first run races out with the wrong toolset.
                disabledReason={updating ? 'Saving scout settings' : undefined}
            />
            {/* Only custom scouts are deletable. A canonical scout would be re-seeded from disk after
                deletion (and couldn't be re-added from the UI), so its terminal action stays disable. */}
            {onDelete && config.scout_origin === 'custom' ? (
                <div className="flex items-center justify-between gap-4 border-t border-primary pt-2">
                    <div className="flex flex-col min-w-0">
                        <span className="text-xs text-default">Delete scout</span>
                        <span className="text-[11.5px] text-muted">Permanently deletes the scout and its skill</span>
                    </div>
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        loading={deleting}
                        disabledReason={deleting ? 'Deleting…' : undefined}
                        onClick={() => confirmDeleteScout(config, onDelete)}
                    >
                        Delete
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}

/**
 * Confirm-then-delete for a custom scout. Deletion archives the scout's skill (the permanent off
 * switch — the coordinator won't re-seed a tombstoned skill or re-create its config) and removes
 * its config. Irreversible, so the dialog steers users toward disable when they only want a pause.
 */
function confirmDeleteScout(config: SignalScoutConfig, onDelete: (configId: string) => void): void {
    const displayName = prettifyScoutSkillName(config.skill_name)
    LemonDialog.open({
        title: `Delete the ${displayName} scout?`,
        description: (
            <span>
                This archives the <span className="font-mono text-[11px]">{config.skill_name}</span> skill and removes
                its config. The scout stops running and won't come back — this can't be undone. To pause a scout without
                deleting it, disable it instead.
            </span>
        ),
        primaryButton: {
            children: 'Delete',
            status: 'danger',
            onClick: () => onDelete(config.id),
        },
        secondaryButton: { children: 'Cancel' },
    })
}
