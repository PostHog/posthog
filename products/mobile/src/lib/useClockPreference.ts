import { useCalendars } from 'expo-localization'

import { prefers24HourClock } from './dates'

export function useClockPreference(): boolean {
    const [calendar] = useCalendars()
    return prefers24HourClock(calendar.uses24hourClock)
}
