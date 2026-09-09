import { useActions, useValues } from 'kea'

import { LemonButton, LemonDropdown, LemonSwitch } from '@posthog/lemon-ui'

import { IconTuning } from 'lib/lemon-ui/icons'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { SURVEY_RESPONSE_CONTEXT_COLUMNS } from 'scenes/surveys/utils'

export function SurveyResponseColumnsMenu(): JSX.Element {
    const { responseContextColumns } = useValues(surveyLogic)
    const { setResponseContextColumn } = useActions(surveyLogic)

    return (
        <LemonDropdown
            closeOnClickInside={false}
            placement="bottom-end"
            overlay={
                <div className="flex flex-col gap-2 py-1 px-2 min-w-64">
                    {SURVEY_RESPONSE_CONTEXT_COLUMNS.map((column) => (
                        <LemonSwitch
                            key={column.key}
                            checked={responseContextColumns.includes(column.key)}
                            onChange={(show) => setResponseContextColumn(column.key, show)}
                            label={column.label}
                            fullWidth
                            data-attr={`survey-response-column-${column.key}`}
                        />
                    ))}
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconTuning />}
                tooltip="Add respondent details to the table and to exports"
                data-attr="survey-response-columns-menu"
            >
                Columns
            </LemonButton>
        </LemonDropdown>
    )
}
