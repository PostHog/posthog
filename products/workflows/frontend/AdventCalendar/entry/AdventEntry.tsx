import { useValues } from 'kea'

import { adventCalendarAccessLogic } from '../adventCalendarAccessLogic'
import { AdventEntryCard } from './AdventEntryCard'

export function AdventEntry(): JSX.Element | null {
    const { calendarOn } = useValues(adventCalendarAccessLogic)
    return calendarOn ? <AdventEntryCard /> : null
}
