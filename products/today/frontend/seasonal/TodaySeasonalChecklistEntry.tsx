import { useValues } from 'kea'

import { todaySeasonalCampaignLogic } from './todaySeasonalCampaignLogic'
import { TodaySeasonalChecklist } from './TodaySeasonalChecklist'

export function TodaySeasonalChecklistEntry(): JSX.Element | null {
    const { campaign } = useValues(todaySeasonalCampaignLogic)

    return campaign ? <TodaySeasonalChecklist key={campaign.campaign} checklist={campaign} /> : null
}
