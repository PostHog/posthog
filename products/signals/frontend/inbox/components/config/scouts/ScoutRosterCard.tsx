import { useActions, useValues } from 'kea'

import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import {
    nextRunAt,
    SCOUT_GROUP_LABEL,
    scoutCadenceLabel,
    ScoutRosterRow,
    scoutSubtitle,
} from '../../../utils/scoutGroups'
import { prettifyScoutSkillName } from '../../../utils/scoutRunsWindow'
import { inboxCardRowClassName } from '../../cards/inboxCardRowClassName'
import { ScoutLifecycleBadge } from './ScoutBadges'
import { ScoutEnabledSwitch } from './ScoutConfigControls'
import { ScoutNextRunLabel } from './ScoutNextRunLabel'
import { ScoutRunBoxes } from './ScoutRunBoxes'
import { ScoutStatusDot } from './ScoutStatusDot'

const SUBTITLE_TONE_CLASS = {
    danger: 'text-danger',
    warning: 'text-warning',
    muted: 'text-secondary',
} as const

function MetaSeparator(): JSX.Element {
    return <span aria-hidden>·</span>
}

/**
 * One scout in the roster, in the same row shape as the report cards: status dot, name, what it
 * last checked, and its cadence on the left; the recent-run strip and the on/off switch on the
 * right. The body links to the scout page. The run boxes and the switch sit outside that link, so
 * a run box opens its task and the switch flips the scout without opening it.
 */
export function ScoutRosterCard({ row }: { row: ScoutRosterRow }): JSX.Element {
    const { config, group } = row
    const { rollups, updatingScoutIds, scoutRunsLoadedOnce } = useValues(scoutFleetLogic)
    const { updateScoutConfig } = useActions(scoutFleetLogic)
    const { currentTeam } = useValues(teamLogic)
    const now = new Date()
    const rollup = rollups.get(config.skill_name)
    const runs = rollup?.runs ?? []
    const subtitle = scoutSubtitle(config, rollup, now)
    // Only enabled scouts have a next run; a paused one would otherwise carry an empty dash.
    const hasNextRun = nextRunAt(config, currentTeam?.timezone ?? 'UTC', now) !== null

    return (
        <div className={cn(inboxCardRowClassName(false), !config.enabled && 'opacity-65')}>
            <Link
                to={urls.inboxScout(config.skill_name)}
                className="flex min-w-0 flex-1 items-start gap-3 text-left text-inherit no-underline"
                data-attr="inbox-scout-card"
            >
                <span className="flex h-5 shrink-0 items-center">
                    <ScoutStatusDot group={group} />
                </span>
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="min-w-0 truncate text-sm font-semibold leading-snug">
                            {prettifyScoutSkillName(config.skill_name)}
                        </span>
                        {config.auto_pause_exempt && group === 'watching' && (
                            <Tooltip title="Exempt from auto-pause, because this scout is supposed to stay quiet">
                                <LemonTag size="small">Quiet by design</LemonTag>
                            </Tooltip>
                        )}
                        <ScoutLifecycleBadge config={config} />
                    </div>
                    {subtitle && (
                        <p className={cn('m-0 line-clamp-1 text-xs leading-snug', SUBTITLE_TONE_CLASS[subtitle.tone])}>
                            {subtitle.text}
                        </p>
                    )}
                    <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs leading-none text-tertiary select-none">
                        <span>{SCOUT_GROUP_LABEL[group]}</span>
                        <MetaSeparator />
                        <span>{scoutCadenceLabel(config)}</span>
                        {hasNextRun && (
                            <>
                                <MetaSeparator />
                                <span className="tabular-nums">
                                    Next run <ScoutNextRunLabel config={config} />
                                </span>
                            </>
                        )}
                    </div>
                </div>
            </Link>
            <div className="flex shrink-0 items-center justify-between gap-4 @lg:justify-end @lg:self-stretch @lg:border-l @lg:border-primary @lg:pl-3">
                {/* A fixed strip width on wide rows keeps every row's newest run on one vertical line. */}
                <div className="flex min-w-0 justify-end @lg:w-52">
                    {runs.length > 0 ? (
                        <ScoutRunBoxes runs={runs} />
                    ) : (
                        // Until the runs request has landed once, an empty rollup means "not
                        // loaded", not "never ran"; the poll retries a failed load on its own.
                        <span className="text-xs text-muted">{scoutRunsLoadedOnce ? 'No runs yet' : '…'}</span>
                    )}
                </div>
                <ScoutEnabledSwitch
                    config={config}
                    onUpdate={updateScoutConfig}
                    updating={updatingScoutIds.includes(config.id)}
                />
            </div>
        </div>
    )
}
