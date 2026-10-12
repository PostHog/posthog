import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { SurveysTabs } from 'scenes/surveys/surveysLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function SurveyGlobalWaitPeriodNote({ surveyDays }: { surveyDays?: number | null }): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const globalDays = currentTeam?.survey_config?.seenSurveyWaitPeriodInDays

    if (!globalDays || (surveyDays ?? 0) >= globalDays) {
        return null
    }

    return (
        <p className="mb-0 text-xs text-secondary">
            This project waits {globalDays} {globalDays === 1 ? 'day' : 'days'} between surveys, so this survey also
            waits at least that long. <Link to={urls.surveys(SurveysTabs.Settings)}>Change it in survey settings</Link>
        </p>
    )
}
