import { BindLogic } from 'kea'
import { useRef } from 'react'

import type { SeasonalChecklistApi } from '../generated/api.schemas'
import { TodaySeasonalChecklistDialog } from './TodaySeasonalChecklistDialog'
import { todaySeasonalChecklistLogic } from './todaySeasonalChecklistLogic'
import { TodaySeasonalHog } from './TodaySeasonalHog'

export function TodaySeasonalChecklist({ checklist }: { checklist: SeasonalChecklistApi }): JSX.Element {
    const cardRef = useRef<HTMLDivElement>(null)

    return (
        <BindLogic logic={todaySeasonalChecklistLogic} props={{ checklist }}>
            <TodaySeasonalHog checklist={checklist} cardRef={cardRef} />
            <TodaySeasonalChecklistDialog ref={cardRef} checklist={checklist} />
        </BindLogic>
    )
}
