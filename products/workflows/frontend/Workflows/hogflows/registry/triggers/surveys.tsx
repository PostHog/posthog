import { useActions, useValues } from 'kea'

import { IconMessage, IconPlusSmall } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { Link } from 'lib/lemon-ui/Link'
import { truncate } from 'lib/utils'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter/TestAccountFilter'
import { urls } from 'scenes/urls'

import { Survey, SurveyEventName, SurveyQuestionType } from '~/types'

import { HogFlowPropertyFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowFilters'
import {
    type EventTriggerConfig,
    registerTriggerType,
} from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

import { HogFlowAction } from '../../types'
import { surveyTriggerLogic } from './surveyTriggerLogic'

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

export function getSurveyResponsePropertyKeys(
    survey: Survey
): { key: string; buttonLabel: string; question: string }[] {
    return survey.questions
        .map((q, index) => {
            if (q.type === SurveyQuestionType.Link) {
                return null
            }
            const key = index === 0 ? '$survey_response' : `$survey_response_${index}`
            return { key, buttonLabel: truncate(q.question, 40), question: q.question }
        })
        .filter(Boolean) as { key: string; buttonLabel: string; question: string }[]
}

const MANAGED_PROPERTY_KEYS = new Set(['$survey_id', '$survey_completed'])

export function getUserProperties(config: EventTriggerConfig): any[] {
    return (config.filters?.properties ?? []).filter((p: any) => !MANAGED_PROPERTY_KEYS.has(p.key))
}

export function buildProperties(
    surveyId: string | null | 'any',
    completedResponsesOnly: boolean,
    userProperties: any[]
): any[] {
    const properties: any[] = []
    if (surveyId === 'any') {
        properties.push({ key: '$survey_id', operator: 'is_set', type: 'event' })
    } else if (surveyId) {
        properties.push({ key: '$survey_id', value: surveyId, operator: 'exact', type: 'event' })
    }
    if (completedResponsesOnly) {
        properties.push({ key: '$survey_completed', value: true, operator: 'exact', type: 'event' })
    }
    return [...properties, ...userProperties]
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
    const userProperties = getUserProperties(config)
    const filterTestAccounts = config.filters?.filter_test_accounts ?? false

    const updateTriggerConfig = (
        surveyId: string | null | 'any',
        completedResponsesOnly: boolean,
        newUserProperties: any[]
    ): void => {
        setWorkflowActionConfig(node.data.id, {
            type: 'event',
            filters: {
                events: [{ id: SurveyEventName.SENT, type: 'events', name: 'Survey sent' }],
                properties: buildProperties(surveyId, completedResponsesOnly, newUserProperties),
                filter_test_accounts: filterTestAccounts,
            },
        })
    }

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
                        updateTriggerConfig(surveyId, completedOnly, userProperties)
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
                        updateTriggerConfig(selectedSurveyId, value === 'completed', userProperties)
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

                if (selectedSurveyId && selectedSurveyId !== 'any' && !surveysLoading && !selectedSurvey) {
                    return (
                        <LemonBanner type="warning" className="w-full">
                            <p>
                                The selected survey could not be found. It may have been deleted. Please select another
                                survey.
                            </p>
                        </LemonBanner>
                    )
                }

                if (selectedSurvey && !selectedSurvey.start_date) {
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

            <LemonField.Pure label="Only trigger for specific answers">
                <div className="flex flex-col gap-2">
                    <HogFlowPropertyFilters
                        filtersKey={`survey-trigger-${node.data.id}`}
                        filters={{ properties: userProperties }}
                        setFilters={(filters) => {
                            updateTriggerConfig(selectedSurveyId, completedOnly, filters?.properties ?? [])
                        }}
                    />
                    {selectedSurvey && selectedSurvey.questions.length > 0 && (
                        <div className="flex flex-col gap-1">
                            <span className="text-xs text-muted">Add filter for a question:</span>
                            <div className="flex flex-wrap gap-1">
                                {getSurveyResponsePropertyKeys(selectedSurvey).map(({ key, buttonLabel, question }) => (
                                    <LemonButton
                                        key={key}
                                        type="secondary"
                                        size="xsmall"
                                        icon={<IconPlusSmall />}
                                        tooltip={question}
                                        onClick={() => {
                                            updateTriggerConfig(selectedSurveyId, completedOnly, [
                                                ...userProperties,
                                                { key, type: 'event' },
                                            ])
                                        }}
                                    >
                                        {buttonLabel}
                                    </LemonButton>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </LemonField.Pure>

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
    group: 'Surveys',
    matchConfig: (config) => isSurveyTriggerConfig(config),
    buildConfig: () => ({
        type: 'event',
        filters: {
            events: [{ id: SurveyEventName.SENT, type: 'events', name: 'Survey sent' }],
            properties: [],
        },
    }),
    validate: (config): { valid: boolean; errors: Record<string, string> } | null => {
        if (config.type !== 'event') {
            return null
        }
        const surveyIdProp = config.filters?.properties?.find((p: any) => p.key === '$survey_id')
        if (!surveyIdProp) {
            return { valid: false, errors: { filters: 'Please select a survey' } }
        }
        return { valid: true, errors: {} }
    },
    ConfigComponent: StepTriggerConfigurationSurvey,
})
