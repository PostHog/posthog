import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'
import { Link } from 'lib/lemon-ui/Link'
import { truncate } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { SurveyApi } from 'products/surveys/frontend/generated/api.schemas'

import { workflowSurveyPickerLogic } from './workflowSurveyPickerLogic'
import { isLimitedToWorkflowRecipients } from './workflowSurveyTargeting'

const IN_APP_SURVEY_TYPES = new Set(['popover', 'widget'])

function surveyStatusLabel(survey: SurveyApi): string {
    if (!survey.start_date) {
        return 'draft'
    }
    return survey.end_date ? 'complete' : 'running'
}

function SurveyReadiness({ survey }: { survey: SurveyApi }): JSX.Element {
    const logic = workflowSurveyPickerLogic({ surveyId: survey.id })
    const { limitingSurveyId } = useValues(logic)
    const { currentTeam } = useValues(teamLogic)
    const { limitToWorkflowRecipients } = useActions(logic)

    if (!IN_APP_SURVEY_TYPES.has(survey.type)) {
        return (
            <LemonBanner type="warning">
                This survey isn't shown inside your app. Pick a popover or widget survey.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {!currentTeam?.surveys_opt_in && (
                <LemonBanner type="warning">
                    Surveys are turned off for this project, so nobody will see this one.{' '}
                    <Link to={urls.settings('environment-surveys', 'surveys-interface')}>Turn them on</Link>
                </LemonBanner>
            )}
            {!survey.start_date ? (
                <LemonBanner type="warning">
                    This survey is a draft. <Link to={urls.survey(survey.id)}>Launch it</Link> so people can see it.
                </LemonBanner>
            ) : survey.end_date ? (
                <LemonBanner type="warning">
                    This survey has ended. <Link to={urls.survey(survey.id)}>Resume it</Link> so people can see it.
                </LemonBanner>
            ) : null}
            {isLimitedToWorkflowRecipients(survey) ? (
                <LemonBanner type="success">Only people this workflow reaches will see this survey.</LemonBanner>
            ) : (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Show only to workflow recipients',
                        onClick: () => limitToWorkflowRecipients(survey),
                        loading: limitingSurveyId === survey.id,
                        disabledReason: limitingSurveyId ? 'Updating the survey...' : undefined,
                        'data-attr': 'workflow-survey-limit-targeting',
                    }}
                >
                    Anyone who matches this survey's display conditions can see it, not only people this workflow
                    reaches.
                </LemonBanner>
            )}
            <div className="text-xs text-secondary">
                The survey appears the next time the person loads your web or mobile app, as long as they haven't
                already answered or dismissed it.
            </div>
        </div>
    )
}

export default function CyclotronJobInputSurveyPicker({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const selectedId = typeof value === 'string' ? value : ''
    const logic = workflowSurveyPickerLogic({ surveyId: selectedId || null })
    const { surveys, surveysLoading, selectedSurvey, selectedSurveyLoading } = useValues(logic)
    const { loadSurveys, loadSelectedSurvey, setSearch } = useActions(logic)

    const currentSurvey = selectedSurvey?.id === selectedId ? selectedSurvey : null
    const options: LemonInputSelectOption[] = surveys
        .filter((survey) => IN_APP_SURVEY_TYPES.has(survey.type) && survey.id !== selectedId)
        .map((survey) => ({
            key: survey.id,
            label: `${truncate(survey.name, 60)} (${surveyStatusLabel(survey)})`,
        }))
    // A stored ID that no longer resolves (deleted) still renders as itself, not blank.
    if (selectedId) {
        options.unshift({
            key: selectedId,
            label: currentSurvey
                ? `${truncate(currentSurvey.name, 60)} (${surveyStatusLabel(currentSurvey)})`
                : selectedSurveyLoading
                  ? 'Loading survey...'
                  : `Unknown survey (${selectedId})`,
        })
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex gap-2 items-center">
                <div className="flex-1 min-w-0">
                    <LemonInputSelect
                        mode="single"
                        data-attr="select-workflow-survey"
                        placeholder="Search surveys..."
                        value={selectedId ? [selectedId] : []}
                        onChange={(val) => onChange(val[0] ?? null)}
                        onInputChange={setSearch}
                        disableFiltering
                        options={options}
                        loading={surveysLoading}
                    />
                </div>
                <LemonButton size="small" type="secondary" to={urls.surveys()} targetBlank>
                    Create survey
                </LemonButton>
                <LemonButton
                    size="small"
                    type="tertiary"
                    onClick={() => {
                        loadSurveys()
                        loadSelectedSurvey(selectedId || null)
                    }}
                    disabledReason={surveysLoading || selectedSurveyLoading ? 'Loading...' : undefined}
                >
                    Refresh
                </LemonButton>
            </div>
            {currentSurvey && !currentSurvey.archived ? (
                <SurveyReadiness survey={currentSurvey} />
            ) : selectedId && !selectedSurveyLoading ? (
                <LemonBanner type="error">This survey was archived or deleted. Pick another one.</LemonBanner>
            ) : null}
        </div>
    )
}
