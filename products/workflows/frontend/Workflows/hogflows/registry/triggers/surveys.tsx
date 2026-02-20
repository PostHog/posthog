import { useActions, useValues } from 'kea'

import { IconMessage } from '@posthog/icons'
import { LemonBanner, LemonInput, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { Link } from 'lib/lemon-ui/Link'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter/TestAccountFilter'
import { urls } from 'scenes/urls'

import { SurveyEventName } from '~/types'

import { registerTriggerType } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

import { surveyTriggerLogic } from '../../steps/surveyTriggerLogic'
import { HogFlowAction } from '../../steps/types'

type EventTriggerConfig = {
    type: 'event'
    filters: {
        events?: any[]
        properties?: any[]
        actions?: any[]
        filter_test_accounts?: boolean
    }
}

export function isSurveyTriggerConfig(config: Extract<HogFlowAction, { type: 'trigger' }>['config']): boolean {
    if (config.type !== 'event') {
        return false
    }
    const events = config.filters?.events ?? []
    return events.length === 1 && events[0]?.id === SurveyEventName.SENT
}

export function getSelectedSurveyId(config: HogFlowAction['config']): string | null | 'any' {
    if (!('type' in config) || config.type !== 'event') {
        return null
    }
    const surveyIdProp = config.filters?.properties?.find((p: any) => p.key === '$survey_id')
    if (!surveyIdProp) {
        return null
    }
    if (surveyIdProp.operator === 'is_set') {
        return 'any'
    }
    return surveyIdProp.value ?? null
}

function getCompletedResponsesOnly(config: EventTriggerConfig): boolean {
    const completedProp = config.filters?.properties?.find((p: any) => p.key === '$survey_completed')
    return completedProp?.value === true
}

function buildProperties(surveyId: string | null | 'any', completedResponsesOnly: boolean): any[] {
    const properties: any[] = []
    if (surveyId === 'any') {
        properties.push({ key: '$survey_id', operator: 'is_set', type: 'event' })
    } else if (surveyId) {
        properties.push({ key: '$survey_id', value: surveyId, operator: 'exact', type: 'event' })
    }
    if (completedResponsesOnly) {
        properties.push({ key: '$survey_completed', value: true, operator: 'exact', type: 'event' })
    }
    return properties
}

function StepTriggerConfigurationSurvey({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const config = node.data.config as EventTriggerConfig
    const {
        allSurveys,
        filteredSurveys,
        searchTerm,
        surveysLoading,
        moreSurveysLoading,
        hasMoreSurveys,
        responseCounts,
    } = useValues(surveyTriggerLogic)
    const { loadMoreSurveys, setSearchTerm } = useActions(surveyTriggerLogic)
    const selectedSurveyId = getSelectedSurveyId(config)
    const completedOnly = getCompletedResponsesOnly(config)
    const filterTestAccounts = config.filters?.filter_test_accounts ?? false

    const selectedSurvey =
        selectedSurveyId && selectedSurveyId !== 'any' ? allSurveys.find((s) => s.id === selectedSurveyId) : null
    const selectedSurveyLabel =
        selectedSurvey?.name ?? (selectedSurveyId && selectedSurveyId !== 'any' ? 'Loading...' : null)

    const surveyOptions = [
        ...(selectedSurveyId && selectedSurveyLabel
            ? [
                  {
                      label: selectedSurveyLabel,
                      value: selectedSurveyId,
                      hidden: true,
                  },
              ]
            : []),
        {
            label: '',
            value: '__search__' as string | null,
            labelInMenu: (
                <LemonInput
                    type="search"
                    placeholder="Search surveys..."
                    autoFocus
                    value={searchTerm}
                    onChange={setSearchTerm}
                    fullWidth
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => {
                        if (e.key !== 'Escape') {
                            e.stopPropagation()
                        }
                    }}
                    className="mb-1"
                />
            ),
        },
        {
            label: 'Any survey',
            value: 'any' as string | null,
            labelInMenu: (
                <div className="flex flex-col py-1">
                    <span className="font-medium">Any survey</span>
                    <span className="text-xs text-muted">Trigger on any survey response</span>
                </div>
            ),
        },
        ...filteredSurveys.map((s) => {
            const responseCount = responseCounts[s.id] ?? 0
            return {
                label: s.name,
                value: s.id,
                labelInMenu: (
                    <div className="flex items-center justify-between py-1 gap-2 w-full">
                        <div className="flex flex-col min-w-0 flex-1">
                            <span className="font-medium truncate">{s.name}</span>
                            <span className="flex items-center gap-2 text-xs text-muted">
                                <span className="flex items-center gap-1">
                                    <span
                                        className={`inline-block w-1.5 h-1.5 rounded-full ${s.start_date ? 'bg-success' : 'bg-muted-alt'}`}
                                    />
                                    {s.start_date ? 'Active' : 'Draft'}
                                </span>
                                {responseCount > 0 && <span>· {responseCount.toLocaleString()} responses</span>}
                            </span>
                        </div>
                        <Link
                            to={urls.survey(s.id)}
                            target="_blank"
                            onClick={(e) => e.stopPropagation()}
                            className="text-muted hover:text-primary shrink-0"
                            title="Open survey"
                        >
                            <IconOpenInNew className="text-base" />
                        </Link>
                    </div>
                ),
            }
        }),
        ...(hasMoreSurveys && !searchTerm
            ? [
                  {
                      label: 'Load more...',
                      value: '__load_more__' as string | null,
                      labelInMenu: (
                          <div className="flex items-center justify-center py-2 text-primary font-medium">
                              {moreSurveysLoading ? (
                                  <>
                                      <Spinner className="mr-2" />
                                      Loading...
                                  </>
                              ) : (
                                  'Load more surveys...'
                              )}
                          </div>
                      ),
                  },
              ]
            : []),
    ]

    return (
        <>
            <LemonField.Pure label="Select a survey">
                <LemonSelect
                    options={surveyOptions}
                    value={selectedSurveyId}
                    loading={surveysLoading}
                    onChange={(surveyId) => {
                        if (surveyId === '__search__') {
                            return
                        }
                        if (surveyId === '__load_more__') {
                            loadMoreSurveys()
                            return
                        }
                        setSearchTerm('')
                        setWorkflowActionConfig(node.data.id, {
                            type: 'event',
                            filters: {
                                events: [{ id: SurveyEventName.SENT, type: 'events', name: 'Survey sent' }],
                                properties: buildProperties(surveyId, completedOnly),
                                filter_test_accounts: filterTestAccounts,
                            },
                        })
                    }}
                    placeholder="Select a survey"
                />
                <p className="text-xs text-muted mt-1">
                    This workflow will be triggered when someone submits a response to this survey.
                </p>
            </LemonField.Pure>

            <LemonField.Pure label="Trigger on">
                <LemonRadio
                    value={completedOnly ? 'completed' : 'any'}
                    onChange={(value) => {
                        const newCompletedOnly = value === 'completed'
                        setWorkflowActionConfig(node.data.id, {
                            type: 'event',
                            filters: {
                                events: [{ id: SurveyEventName.SENT, type: 'events', name: 'Survey sent' }],
                                properties: buildProperties(selectedSurveyId, newCompletedOnly),
                                filter_test_accounts: filterTestAccounts,
                            },
                        })
                    }}
                    options={[
                        {
                            value: 'completed',
                            label: 'Completed responses only',
                            description: 'Trigger only when the survey is fully completed',
                        },
                        {
                            value: 'any',
                            label: 'Any response (including partial)',
                            description:
                                "Trigger on every response, including partial submissions when a user answers some questions but doesn't complete the survey",
                        },
                    ]}
                />
            </LemonField.Pure>

            {(() => {
                if (selectedSurveyId === 'any' && !surveysLoading && allSurveys.length === 0) {
                    return (
                        <LemonBanner type="warning" className="w-full">
                            <p>
                                You don't have any surveys yet. This workflow won't be triggered until you create your
                                first survey.{' '}
                                <Link to={urls.survey('new')} target="_blank" className="font-semibold">
                                    Create a survey <IconOpenInNew className="inline text-sm" />
                                </Link>
                            </p>
                        </LemonBanner>
                    )
                }

                const survey = selectedSurveyId ? allSurveys.find((s) => s.id === selectedSurveyId) : null
                if (survey && !survey.start_date) {
                    return (
                        <LemonBanner type="warning" className="w-full">
                            <p>
                                This survey is not active yet. The workflow won't be triggered until the survey is
                                launched and actively receiving responses.
                            </p>
                        </LemonBanner>
                    )
                }

                return null
            })()}

            <TestAccountFilter
                filters={{ filter_test_accounts: filterTestAccounts }}
                onChange={({ filter_test_accounts }) =>
                    setWorkflowActionConfig(node.data.id, {
                        type: 'event',
                        filters: { ...config.filters, filter_test_accounts },
                    })
                }
            />
        </>
    )
}

registerTriggerType({
    value: 'survey_response',
    label: 'Survey response',
    icon: <IconMessage />,
    description: 'Trigger when a user submits a survey response',
    matchConfig: (config) => isSurveyTriggerConfig(config),
    buildConfig: () => ({
        type: 'event',
        filters: {
            events: [{ id: SurveyEventName.SENT, type: 'events', name: 'Survey sent' }],
            properties: [],
        },
    }),
    ConfigComponent: StepTriggerConfigurationSurvey,
})
