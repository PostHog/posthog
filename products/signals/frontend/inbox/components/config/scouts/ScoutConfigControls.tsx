import { useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonSelect, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { describeCron } from 'lib/cron'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import type {
    PatchedSignalScoutConfigUpdateApi as SignalScoutConfigUpdate,
    SignalScoutConfigApi as SignalScoutConfig,
} from 'products/signals/frontend/generated/api.schemas'
import { SignalScoutConfigNetworkAccessEnumApi } from 'products/signals/frontend/generated/api.schemas'

import {
    dailyCronToTime,
    dayTimeToWeeklyCron,
    DEFAULT_SCOUT_DAILY_TIME,
    DEFAULT_SCOUT_WEEKLY_DAY,
    getScoutScheduleMode,
    getScoutScheduleOptions,
    prettifyScoutSkillName,
    SCOUT_CRON_MAX_LENGTH,
    SCOUT_CUSTOM_CRON_SCHEDULE_MODE,
    SCOUT_DAILY_AT_SCHEDULE_MODE,
    SCOUT_WEEKDAY_OPTIONS,
    SCOUT_WEEKLY_ON_SCHEDULE_MODE,
    scoutCronScheduleError,
    timeToDailyCron,
    weeklyCronToDayTime,
} from '../../../utils/scoutRunsWindow'
import { ScoutMcpServersPicker } from './ScoutMcpServersPicker'
import { ScoutSlackDestination } from './ScoutSlackDestination'
import { ScoutTagsEditor } from './ScoutTagsEditor'

interface ScoutConfigControlsProps {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    updating?: boolean
}

// The models the picker offers, a deliberate subset of the Tasks catalog the backend
// validates pins against — growing this list is a frontend-only change.
const SCOUT_MODEL_OPTIONS: { value: string | null; label: string }[] = [
    { value: null, label: 'Default' },
    { value: 'gpt-5.6-luna', label: 'GPT-5.6 Luna' },
    { value: 'gpt-5.6-terra', label: 'GPT-5.6 Terra' },
    { value: 'gpt-5.6-sol', label: 'GPT-5.6 Sol' },
]

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
    const weekly = weeklyCronToDayTime(config.run_cron_schedule)
    const runTime = dailyCronToTime(config.run_cron_schedule) ?? weekly?.time ?? DEFAULT_SCOUT_DAILY_TIME
    const weeklyDay = weekly?.day ?? DEFAULT_SCOUT_WEEKLY_DAY
    const savedScheduleMode = getScoutScheduleMode(config)
    // The saved config cannot express "the user opened the custom mode but has not typed a valid
    // expression yet", so the picked mode is held here until a write settles it.
    const [pickedScheduleMode, setPickedScheduleMode] = useState<string | null>(null)
    const scheduleMode = pickedScheduleMode ?? savedScheduleMode
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
                        A rolling cadence, a set time each day or week, or a cron expression
                    </span>
                </div>
                <LemonSelect
                    size="small"
                    value={scheduleMode}
                    options={getScoutScheduleOptions(config, { customCronEditable: true })}
                    disabledReason={controlsDisabledReason}
                    className="w-44"
                    onChange={(value) => {
                        setPickedScheduleMode(value)
                        if (value === savedScheduleMode || value === SCOUT_CUSTOM_CRON_SCHEDULE_MODE) {
                            return
                        }
                        if (value === SCOUT_DAILY_AT_SCHEDULE_MODE) {
                            onUpdate(config.id, { run_cron_schedule: timeToDailyCron(runTime) })
                            return
                        }
                        if (value === SCOUT_WEEKLY_ON_SCHEDULE_MODE) {
                            onUpdate(config.id, { run_cron_schedule: dayTimeToWeeklyCron(weeklyDay, runTime) })
                            return
                        }
                        // A rolling cadence replaces any cron — the schedule is one or the other.
                        onUpdate(config.id, { run_interval_minutes: Number(value), run_cron_schedule: null })
                    }}
                />
            </div>
            {scheduleMode === SCOUT_WEEKLY_ON_SCHEDULE_MODE ? (
                <div className="flex items-center justify-between gap-4">
                    <div className="flex flex-col min-w-0">
                        <span className="text-xs text-default">Run day</span>
                        <span className="text-[11.5px] text-muted">The scout runs once a week, on this day</span>
                    </div>
                    <LemonSelect
                        size="small"
                        value={weeklyDay}
                        options={SCOUT_WEEKDAY_OPTIONS}
                        disabledReason={controlsDisabledReason}
                        className="w-44"
                        onChange={(value) => {
                            const runCronSchedule = dayTimeToWeeklyCron(value, runTime)
                            if (runCronSchedule !== config.run_cron_schedule) {
                                onUpdate(config.id, { run_cron_schedule: runCronSchedule })
                            }
                        }}
                        aria-label={`${config.skill_name} run day`}
                    />
                </div>
            ) : null}
            {scheduleMode === SCOUT_DAILY_AT_SCHEDULE_MODE || scheduleMode === SCOUT_WEEKLY_ON_SCHEDULE_MODE ? (
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
                        defaultValue={runTime}
                        disabledReason={controlsDisabledReason}
                        className="w-44"
                        onBlur={(event) => {
                            const value = event.currentTarget.value
                            // Empty means a half-finished edit, never "clear" — turning the
                            // schedule off is the select's job, so just fall back to the saved time.
                            if (!value) {
                                return
                            }
                            const runCronSchedule =
                                scheduleMode === SCOUT_WEEKLY_ON_SCHEDULE_MODE
                                    ? dayTimeToWeeklyCron(weeklyDay, value)
                                    : timeToDailyCron(value)
                            if (runCronSchedule !== config.run_cron_schedule) {
                                onUpdate(config.id, { run_cron_schedule: runCronSchedule })
                            }
                        }}
                    />
                </div>
            ) : null}
            {scheduleMode === SCOUT_CUSTOM_CRON_SCHEDULE_MODE ? (
                <ScoutCustomCronField
                    config={config}
                    onUpdate={onUpdate}
                    disabledReason={controlsDisabledReason}
                    projectTimezone={projectTimezone}
                />
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
                        { value: SignalScoutConfigNetworkAccessEnumApi.Trusted, label: 'Trusted domains' },
                        { value: SignalScoutConfigNetworkAccessEnumApi.Full, label: 'Full access' },
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
                            The model this scout runs on. Pick a more capable model for harder tasks.
                        </span>
                    </div>
                    <LemonSelect
                        size="small"
                        value={config.model ?? null}
                        // A pin stored via the API can name a catalog model the picker doesn't offer;
                        // keep it selected (hidden from the menu) so opening the picker doesn't lose it.
                        options={
                            config.model && !SCOUT_MODEL_OPTIONS.some((option) => option.value === config.model)
                                ? [...SCOUT_MODEL_OPTIONS, { value: config.model, label: config.model, hidden: true }]
                                : SCOUT_MODEL_OPTIONS
                        }
                        // Editable while the scout is disabled for the same reason as network access:
                        // a newly enabled scout is immediately due, so the model must be settable first.
                        disabledReason={updating ? 'Saving scout settings' : undefined}
                        className="w-44"
                        onChange={(value) => {
                            if (value !== (config.model ?? null)) {
                                onUpdate(config.id, { model: value })
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
 * Raw cron editor for the schedule the presets cannot express — weekday runs, several days a week,
 * monthly. Validated against the same rules the config API applies, so a typo is caught before the
 * PATCH, and saved on blur or Enter.
 */
function ScoutCustomCronField({
    config,
    onUpdate,
    disabledReason,
    projectTimezone,
}: {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    disabledReason?: string
    projectTimezone: string
}): JSX.Element {
    const [draft, setDraft] = useState(config.run_cron_schedule ?? '')
    const expression = draft.trim()
    // An empty field is a half-finished edit, not a mistake, so it stays neutral and saves nothing.
    const error = expression ? scoutCronScheduleError(expression) : null
    const hint = error ?? describeCron(expression)
    const save = (): void => {
        if (!expression || error || expression === config.run_cron_schedule) {
            return
        }
        onUpdate(config.id, { run_cron_schedule: expression })
    }

    return (
        <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col min-w-0">
                <span className="text-xs text-default">Cron expression</span>
                <span className="text-[11.5px] text-muted">
                    Minute, hour, day of month, month, day of week, in the project timezone ({projectTimezone})
                </span>
            </div>
            <div className="flex flex-col gap-1 w-44 shrink-0">
                <LemonInput
                    size="small"
                    value={draft}
                    placeholder="0 9 * * 1-5"
                    maxLength={SCOUT_CRON_MAX_LENGTH}
                    className="font-mono"
                    status={error ? 'danger' : 'default'}
                    disabledReason={disabledReason}
                    onChange={setDraft}
                    onBlur={save}
                    onPressEnter={save}
                    aria-label={`${config.skill_name} cron expression`}
                />
                {hint ? <span className={`text-[11.5px] ${error ? 'text-danger' : 'text-muted'}`}>{hint}</span> : null}
            </div>
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
