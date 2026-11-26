import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { todaySeasonalChecklistLogic } from './todaySeasonalChecklistLogic'

export function TodaySeasonalOpenButton({ label }: { label: string }): JSX.Element | null {
    const { dismissed } = useValues(todaySeasonalChecklistLogic)
    const { openChecklist } = useActions(todaySeasonalChecklistLogic)

    return dismissed ? null : (
        <div className="mb-8 flex">
            <Button variant="outline" onClick={openChecklist} data-attr="today-seasonal-checklist-open">
                {label}
            </Button>
        </div>
    )
}
