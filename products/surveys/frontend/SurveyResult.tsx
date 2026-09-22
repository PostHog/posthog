import { useActions, useValues } from 'kea'

import { IconGraph } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import 'scenes/surveys/SurveyView.scss'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SurveyQuestionVisualization } from 'scenes/surveys/components/question-visualizations/SurveyQuestionVisualization'
import { SurveyNotificationsCallout } from 'scenes/surveys/components/SurveyNotificationsCallout'
import { SurveyResultsRefreshStatus } from 'scenes/surveys/components/SurveyResultsRefreshStatus'
import { NEW_SURVEY } from 'scenes/surveys/constants'
import { useSurveyResponseColumns } from 'scenes/surveys/hooks/useSurveyResponseColumns'
import { SurveyHeadline } from 'scenes/surveys/SurveyHeadline'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { SurveyNoResponsesBanner } from 'scenes/surveys/SurveyNoResponsesBanner'
import { SurveyResponseFilters } from 'scenes/surveys/SurveyResponseFilters'
import { SurveyStatsSummary } from 'scenes/surveys/SurveyStatsSummary'
import { SurveyResponseExpandedRow } from 'scenes/surveys/SurveyViewRedesign/SurveyResponseExpandedRow'
import { transformSurveyResponseRows } from 'scenes/surveys/utils'

import { Query } from '~/queries/Query/Query'
import { SurveyEventName, SurveyQuestionType } from '~/types'

function SurveyResponsesByQuestionV2(): JSX.Element {
    const { survey } = useValues(surveyLogic)

    return (
        <div className="flex flex-col gap-2">
            {survey.questions.map((question, i) => {
                if (!question.id || question.type === SurveyQuestionType.Link) {
                    return null
                }
                return (
                    <div key={question.id} className="flex flex-col gap-2">
                        <SurveyQuestionVisualization question={question} questionIndex={i} />
                        <LemonDivider />
                    </div>
                )
            })}
        </div>
    )
}

export function SurveyResult({ disableEventsTable }: { disableEventsTable?: boolean }): JSX.Element {
    const {
        survey,
        dataTableQuery,
        surveyLoading,
        surveyAsInsightURL,
        isAnyResultsLoading,
        resultsRequeryInProgress,
        processedSurveyStats,
        archivedResponseUuids,
        isSurveyHeadlineEnabled,
        hasActiveFilters,
        hasActiveAnswerFilters,
        hasActiveDateRange,
        propertyFilters,
    } = useValues(surveyLogic)
    const { clearFilters } = useActions(surveyLogic)
    const isInitialSurveyLoad = surveyLoading && survey.id === NEW_SURVEY.id
    const surveyColumnRenderers = useSurveyResponseColumns()

    const atLeastOneResponse = !!processedSurveyStats?.[SurveyEventName.SENT].total_count
    const isRefreshingResults = resultsRequeryInProgress || isAnyResultsLoading
    return (
        <div className="deprecated-space-y-4">
            {isSurveyHeadlineEnabled && <SurveyHeadline />}
            <SurveyResponseFilters />
            <SurveyNotificationsCallout surveyId={survey.id} />
            {isRefreshingResults || atLeastOneResponse ? (
                <>
                    <SurveyResultsRefreshStatus visible={isRefreshingResults} />
                    <div
                        aria-busy={isRefreshingResults}
                        className={
                            isRefreshingResults
                                ? 'opacity-75 transition-opacity duration-200 ease-out'
                                : 'opacity-100 transition-opacity duration-200 ease-out'
                        }
                    >
                        <SurveyStatsSummary />
                        <SurveyResponsesByQuestionV2 />
                        <LemonButton
                            type="primary"
                            data-attr="survey-results-explore"
                            icon={<IconGraph />}
                            to={surveyAsInsightURL}
                            className="max-w-40"
                        >
                            Explore results
                        </LemonButton>
                        {!disableEventsTable &&
                            (isInitialSurveyLoad ? (
                                <LemonSkeleton />
                            ) : (
                                <div className="survey-table-results">
                                    <Query
                                        query={dataTableQuery}
                                        context={{
                                            columns: surveyColumnRenderers,
                                            expandable: {
                                                expandedRowRender: ({ result }) => (
                                                    <SurveyResponseExpandedRow result={result} />
                                                ),
                                                rowExpandable: ({ result }) => !!result,
                                                noIndent: true,
                                            },
                                            dataTableExportExcludedColumns: ['response', 'actions'],
                                            dataTableRowsTransformer: (rows) =>
                                                transformSurveyResponseRows(rows, survey),
                                            rowProps: (record: unknown) => {
                                                // "mute" archived records
                                                if (typeof record !== 'object' || !record || !('result' in record)) {
                                                    return {}
                                                }
                                                const result = record.result
                                                if (!Array.isArray(result)) {
                                                    return {}
                                                }
                                                return {
                                                    className:
                                                        result[0]?.uuid && archivedResponseUuids.has(result[0].uuid)
                                                            ? 'opacity-50'
                                                            : undefined,
                                                }
                                            },
                                        }}
                                    />
                                </div>
                            ))}
                    </div>
                </>
            ) : (
                <>
                    <SurveyStatsSummary />
                    <SurveyNoResponsesBanner
                        type="survey"
                        isFiltered={hasActiveFilters}
                        onClearFilters={hasActiveFilters ? clearFilters : undefined}
                        activeFilterTypes={{
                            dateRange: hasActiveDateRange,
                            answerFilters: hasActiveAnswerFilters,
                            propertyFilters: propertyFilters.length > 0,
                        }}
                    />
                </>
            )}
        </div>
    )
}
