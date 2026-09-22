/** The schedule vocabulary the scout settings UI offers, all expressed as five-field crons so the
 * scheduler's cron path is the only one these scouts use. Crons written outside Vision that don't
 * match one of these shapes surface as custom and stay untouched. */

export type ScoutFrequency = 'daily' | 'weekdays' | 'weekly'

export interface ScoutCadence {
    frequency: ScoutFrequency
    /** HH:MM, in the project timezone the cron is evaluated in. */
    time: string
}

const CRON_RE = /^(\d{1,2}) (\d{1,2}) \* \* (\*|1-5|1)$/

const DAY_FIELD_BY_FREQUENCY: Record<ScoutFrequency, string> = {
    daily: '*',
    weekdays: '1-5',
    weekly: '1',
}

export const SCOUT_FREQUENCY_OPTIONS: { value: ScoutFrequency; label: string }[] = [
    { value: 'daily', label: 'Every day' },
    { value: 'weekdays', label: 'Weekdays' },
    { value: 'weekly', label: 'Weekly (Mondays)' },
]

export function parseScoutCadence(cron: string | null | undefined): ScoutCadence | null {
    const match = cron?.trim().match(CRON_RE)
    if (!match) {
        return null
    }
    const [, minutes, hours, dayField] = match
    const frequency = (Object.entries(DAY_FIELD_BY_FREQUENCY).find(([, field]) => field === dayField)?.[0] ??
        'daily') as ScoutFrequency
    return {
        frequency,
        time: `${hours.padStart(2, '0')}:${minutes.padStart(2, '0')}`,
    }
}

export function scoutCadenceToCron(cadence: ScoutCadence): string {
    const [hours, minutes] = cadence.time.split(':')
    return `${Number(minutes)} ${Number(hours)} * * ${DAY_FIELD_BY_FREQUENCY[cadence.frequency]}`
}
