import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { nextRunAt, scoutCadenceLabel } from '../../../utils/scoutGroups'
import { prettifyScoutSkillName, SCOUT_RUNS_PER_SCOUT, ScoutRollup } from '../../../utils/scoutRunsWindow'
import { ScoutStatusTag } from './ScoutBadges'
import { ScoutEnabledSwitch } from './ScoutConfigControls'
import { LeaveScoutNoteButton } from './ScoutNotesPanel'
import { ScoutSettingsButton } from './ScoutSettingsModal'

function Metric({ value, label }: { value: React.ReactNode; label: string }): JSX.Element {
    return (
        <div className="flex flex-1 flex-col border-r border-primary px-3 py-1.5 last:border-r-0">
            <span className="text-sm font-semibold tabular-nums leading-tight">{value}</span>
            <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
        </div>
    )
}

/**
 * The scout page header: what it is, the controls that act on it, and the numbers that say whether
 * it is worth keeping on.
 */
export function ScoutDetailHeader({
    config,
    rollup,
    noteCount,
    learnedCount,
}: {
    config: SignalScoutConfig
    rollup: ScoutRollup | undefined
    noteCount: number
    learnedCount: number
}): JSX.Element {
    const { updatingScoutIds, manualRunScoutIds } = useValues(scoutFleetLogic)
    const { updateScoutConfig, runScoutNow } = useActions(scoutFleetLogic)
    const { currentTeam } = useValues(teamLogic)

    const updating = updatingScoutIds.includes(config.id)
    const running = manualRunScoutIds.includes(config.id)
    const next = nextRunAt(config, currentTeam?.timezone ?? 'UTC', new Date())
    // Reports filed only — adding the weak-signal count on top produced a total of two different
    // things, which is exactly what made the old "filed" number unreadable.
    const authored = rollup?.authoredReportIds.size ?? 0

    return (
        <div className="flex flex-col gap-3 border-b border-primary bg-surface-primary px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
                <h2 className="mb-0 text-lg font-semibold">{prettifyScoutSkillName(config.skill_name)}</h2>
                <LemonTag size="small" type={config.scout_origin === 'canonical' ? 'muted' : 'highlight'}>
                    {config.scout_origin === 'canonical' ? 'Canonical' : 'Custom'}
                </LemonTag>
                <ScoutStatusTag config={config} />
                <span className="flex-1" />
                <Tooltip title="Dispatch a run now, outside the schedule. Counts against the project's daily run budget.">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconRefresh />}
                        loading={running}
                        disabledReason={running ? 'Starting a run' : undefined}
                        onClick={() => runScoutNow(config.id)}
                    >
                        Run now
                    </LemonButton>
                </Tooltip>
                <ScoutSettingsButton config={config} surface="scout_detail" showLabel />
                <ScoutEnabledSwitch config={config} onUpdate={updateScoutConfig} updating={updating} />
            </div>

            {config.description && (
                <p className="mb-0 max-w-4xl text-sm leading-snug text-secondary">{config.description}</p>
            )}

            <div className="flex flex-wrap rounded border border-primary">
                <Metric value={scoutCadenceLabel(config)} label="Cadence" />
                <Metric
                    value={next ? <TZLabel time={next.toISOString()} /> : <span className="text-muted">—</span>}
                    label="Next run"
                />
                <Metric value={rollup?.runCount ?? 0} label={`Runs · last ${SCOUT_RUNS_PER_SCOUT}`} />
                <Metric value={authored} label="Reports filed" />
                <Metric value={learnedCount} label="Learned" />
                <Metric value={noteCount} label="Told" />
            </div>
        </div>
    )
}

/**
 * The one thing to do about a scout the scheduler has flagged, stated in the words of the reason it
 * recorded. A paused or warned scout is the only case where a page should tell you what to do, so
 * this renders for nothing else.
 */
export function ScoutAttentionBanner({ config }: { config: SignalScoutConfig }): JSX.Element | null {
    const { updatingScoutIds } = useValues(scoutFleetLogic)
    const { updateScoutConfig } = useActions(scoutFleetLogic)
    const updating = updatingScoutIds.includes(config.id)

    if (config.status !== 'paused_by_system' && config.status !== 'pending_pause') {
        return null
    }

    const paused = config.status === 'paused_by_system'
    let headline: string
    let detail: string
    if (config.pause_reason === 'repeated_failures') {
        headline = 'This scout paused itself after its runs kept failing'
        detail = `${pluralize(
            config.consecutive_failure_count,
            'run'
        )} in a row failed. It retries about once a day on its own, and resumes its normal schedule after one clean run. Turning it on resumes it now.`
    } else if (config.pause_reason === 'ignored') {
        headline = paused
            ? 'This scout was paused because nobody acted on its reports'
            : 'This scout pauses soon unless something changes'
        detail =
            'Nothing came of the reports it filed recently. Tell it what to look at instead, or opt it out of auto-pause in settings if the reports are worth keeping.'
    } else {
        headline = paused ? 'This scout was paused after surfacing nothing' : 'This scout has been quiet for two weeks'
        detail =
            "It keeps running, but it's worth checking it's still watching the right things. If quiet is the point, opt it out of auto-pause in settings."
    }

    return (
        <div className="flex flex-col gap-2 rounded border border-danger bg-danger-highlight px-4 py-3">
            <span className="text-sm font-medium text-default">{headline}</span>
            <span className="text-xs leading-snug text-secondary">{detail}</span>
            <div className="flex flex-wrap items-center gap-2">
                {!config.enabled && (
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        loading={updating}
                        onClick={() => updateScoutConfig(config.id, { enabled: true })}
                    >
                        Resume it
                    </LemonButton>
                )}
                {config.enabled && !config.auto_pause_exempt && (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        loading={updating}
                        onClick={() => updateScoutConfig(config.id, { auto_pause_exempt: true })}
                    >
                        Keep it running
                    </LemonButton>
                )}
                <LeaveScoutNoteButton skillName={config.skill_name} size="xsmall" type="tertiary" />
            </div>
        </div>
    )
}
