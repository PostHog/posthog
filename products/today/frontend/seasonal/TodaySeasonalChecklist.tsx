import { BindLogic } from 'kea'

import type { SeasonalChecklistApi } from '../generated/api.schemas'
import { TodaySeasonalChecklistDialog } from './TodaySeasonalChecklistDialog'
import { todaySeasonalChecklistLogic } from './todaySeasonalChecklistLogic'
import { TodaySeasonalOpenButton } from './TodaySeasonalOpenButton'

export function TodaySeasonalChecklist({ checklist }: { checklist: SeasonalChecklistApi }): JSX.Element {
    return (
        <BindLogic logic={todaySeasonalChecklistLogic} props={{ checklist }}>
            <TodaySeasonalOpenButton label={checklist.bubble} />
            <TodaySeasonalChecklistDialog checklist={checklist} />
        </BindLogic>
    )
}
