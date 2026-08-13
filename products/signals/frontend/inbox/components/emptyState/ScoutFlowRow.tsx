import { useValues } from 'kea'

import { IconClock, IconCompass } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { dailyCronToTime, formatRunIntervalShort, prettifyScoutSkillName } from '../../utils/scoutRunsWindow'
import { scoutNextRun } from './scoutNextRun'

function scoutSchedule(config: SignalScoutConfigApi): string {
    if (config.run_cron_schedule) {
        const dailyTime = dailyCronToTime(config.run_cron_schedule)
        return dailyTime ? `Daily at ${dailyTime}` : 'On a set schedule'
    }
    return formatRunIntervalShort(config.run_interval_minutes)
}

export function ScoutFlowRow({ scout }: { scout: SignalScoutConfigApi }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const nextRun = scoutNextRun(scout, currentTeam?.timezone)

    return (
        <div className="grid grid-cols-[2rem_minmax(0,1fr)] gap-3 border-b border-primary px-1 py-3 last:border-b-0 sm:grid-cols-[2rem_minmax(0,1fr)_9.5rem]">
            <div className="relative flex size-8 shrink-0 items-center justify-center rounded-full border border-primary bg-bg-light text-accent">
                <IconCompass />
                <span
                    className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full border-2 border-bg-light bg-success motion-safe:animate-pulse"
                    aria-hidden
                />
            </div>
            <div className="flex min-w-0 flex-col gap-1">
                <span className="truncate text-sm font-medium">{prettifyScoutSkillName(scout.skill_name)}</span>
                <span className="truncate text-xs text-tertiary">
                    Checks {scout.description.trim() || 'your product data'} and reports useful findings.
                </span>
            </div>
            <div className="col-start-2 flex items-center justify-between gap-3 text-xs sm:col-start-auto sm:flex-col sm:items-end sm:justify-center">
                <span className="flex items-center gap-1 font-medium text-primary">
                    <IconClock className="size-3.5 text-tertiary" />
                    {nextRun ? (
                        <>
                            Next run <TZLabel time={nextRun} showPopover={false} noStyles />
                        </>
                    ) : (
                        'Due now'
                    )}
                </span>
                <span className="text-tertiary">{scoutSchedule(scout)}</span>
            </div>
        </div>
    )
}
