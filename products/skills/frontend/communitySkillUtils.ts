import type { CommunitySkillScoutConfigApi } from './generated/api.schemas'

export function communityScoutCadenceLabel(config: CommunitySkillScoutConfigApi | undefined): string {
    if (config?.run_cron_schedule) {
        return 'Runs on a set schedule'
    }
    const minutes = config?.run_interval_minutes ?? 1440
    if (minutes < 60 || minutes % 60 !== 0) {
        return `Runs every ${minutes} minutes`
    }
    if (minutes < 1440 || minutes % 1440 !== 0) {
        return `Runs every ${minutes / 60} hours`
    }
    const days = minutes / 1440
    return days === 1 ? 'Runs daily' : `Runs every ${days} days`
}
