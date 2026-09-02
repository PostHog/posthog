import { dayjs } from 'lib/dayjs'
import { nextCronDate } from 'lib/utils/nextCronDate'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

type ScoutSchedule = Pick<SignalScoutConfigApi, 'last_run_at' | 'run_cron_schedule' | 'run_interval_minutes'>

export function scoutNextRun(
    scout: ScoutSchedule,
    timezone: string | undefined,
    currentDate: Date = new Date()
): dayjs.Dayjs | null {
    if (scout.run_cron_schedule) {
        const scheduleAnchor = scout.last_run_at ? new Date(scout.last_run_at) : currentDate
        const nextRun = nextCronDate(scout.run_cron_schedule, scheduleAnchor, timezone)
        return nextRun && dayjs(nextRun).isAfter(currentDate) ? dayjs(nextRun) : null
    }
    if (!scout.last_run_at) {
        return null
    }
    const nextRun = dayjs(scout.last_run_at).add(scout.run_interval_minutes, 'minute')
    return nextRun.isAfter(currentDate) ? nextRun : null
}
