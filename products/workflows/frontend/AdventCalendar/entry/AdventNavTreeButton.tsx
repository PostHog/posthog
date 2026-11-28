import { useValues } from 'kea'

import type { CategorySuffixNav } from '~/layout/panel-layout/ProjectTree/CustomCategorySuffix'

import { adventCalendarAccessLogic } from '../adventCalendarAccessLogic'
import { AdventClassicNavTreeButton } from './AdventClassicNavTreeButton'
import { AdventTodayNavTreeButton } from './AdventTodayNavTreeButton'

export function AdventNavTreeButton({ nav }: { nav: CategorySuffixNav }): JSX.Element | null {
    const { calendarOn } = useValues(adventCalendarAccessLogic)
    if (!calendarOn) {
        return null
    }
    return nav === 'today' ? <AdventTodayNavTreeButton /> : <AdventClassicNavTreeButton />
}
