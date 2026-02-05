import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo, useState } from 'react'

import {
    IconBolt,
    IconButton,
    IconClock,
    IconLeave,
    IconMessage,
    IconPeople,
    IconPlusSmall,
    IconTarget,
    IconWebhooks,
} from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCalendarSelectInput,
    LemonCheckbox,
    LemonCollapse,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonTag,
    Spinner,
    Tooltip,
    lemonToast,
} from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { Link } from 'lib/lemon-ui/Link'
import { IconAdsClick, IconOpenInNew } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber } from 'lib/utils'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter/TestAccountFilter'
import { urls } from 'scenes/urls'

import { PropertyFilterType, SurveyEventName } from '~/types'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowEventFilters } from '../filters/HogFlowFilters'
import { HogFlowAction } from '../types'
import { batchTriggerLogic } from './batchTriggerLogic'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'
import { surveyTriggerLogic } from './surveyTriggerLogic'

function isSurveyTriggerConfig(config: HogFlowAction['config']): boolean {
    if (!('type' in config) || config.type !== 'event') {
        return false
    }
    const events = config.filters?.events ?? []
    return events.length === 1 && events[0]?.id === SurveyEventName.SENT
}

function getSelectedSurveyId(config: HogFlowAction['config']): string | null {
    if (!('type' in config) || config.type !== 'event') {
        return null
    }
    const surveyIdProp = config.filters?.properties?.find((p: any) => p.key === '$survey_id')
    return surveyIdProp?.value ?? null
}

export function StepTriggerConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'trigger' }>>
}): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const type = 'type' in node.data.config ? node.data.config.type : undefined
    const validationResult = actionValidationErrorsById[node.id]

    const triggerOptions = [
        {
            label: 'Event',
            value: 'event',
            icon: <IconBolt />,
            labelInMenu: (
                <div className="flex flex-col my-1">
                    <div className="font-semibold">Event</div>
                    <p className="text-xs text-muted">
                        Trigger your workflow based on incoming realtime PostHog events
                    </p>
                </div>
            ),
        },
        {
            label: 'Webhook',
            value: 'webhook',
            icon: <IconWebhooks />,
            labelInMenu: (
                <div className="flex flex-col my-1">
                    <div className="font-semibold">Webhook</div>
                    <p className="text-xs text-muted">Trigger your workflow using an incoming HTTP webhook</p>
                </div>
            ),
        },
        {
            label: 'Manual',
            value: 'manual',
            icon: <IconButton />,
            labelInMenu: (
                <div className="flex flex-col my-1">
                    <div className="font-semibold">Manual</div>
                    <p className="text-xs text-muted">Trigger your workflow manually... with a button!</p>
                </div>
            ),
        },
        {
            label: 'Schedule',
            value: 'schedule',
            icon: <IconClock />,
            labelInMenu: (
                <div className="flex flex-col my-1">
                    <div className="font-semibold">Schedule</div>
                    <p className="text-xs text-muted">Schedule your workflow to run at a specific time in the future</p>
                </div>
            ),
        },
        {
            label: 'Tracking pixel',
            value: 'tracking_pixel',
            icon: <IconAdsClick />,
            labelInMenu: (
                <div className="flex flex-col my-1">
                    <div className="font-semibold">Tracking pixel</div>
                    <p className="text-xs text-muted">Trigger your workflow using a 1x1 tracking pixel</p>
                </div>
            ),
        },
    ]

    if (featureFlags[FEATURE_FLAGS.WORKFLOWS_BATCH_TRIGGERS]) {
        triggerOptions.splice(4, 0, {
            label: 'Batch',
            value: 'batch',
            icon: <IconPeople />,
            labelInMenu: (
                <div className="flex flex-col my-1">
                    <div className="font-semibold">Batch</div>
                    <p className="text-xs text-muted">
                        Trigger or schedule your workflow to run for each person in a group you define.
                    </p>
                </div>
            ),
        })
    }

    // if (featureFlags[FEATURE_FLAGS.WORKFLOWS_SURVEY_TRIGGERS]) {
    triggerOptions.splice(1, 0, {
        label: 'Survey',
        value: 'survey',
        icon: <IconMessage />,
        labelInMenu: (
            <div className="flex flex-col my-1">
                <div className="font-semibold">Survey response</div>
                <p className="text-xs text-muted">Trigger when a user submits a survey response</p>
            </div>
        ),
    })
    // }

    // For display purposes, detect if this is a survey trigger (event trigger with 'survey sent' event)
    const displayType = isSurveyTriggerConfig(node.data.config) ? 'survey' : type

    return (
        <div className="flex flex-col items-start w-full gap-2" data-attr="workflow-trigger">
            <span className="flex gap-1">
                <IconBolt className="text-lg" />
                <span className="text-md font-semibold">Trigger type</span>
            </span>
            <span>What causes this workflow to begin?</span>
            <LemonField.Pure error={validationResult?.errors?.type}>
                <LemonSelect
                    options={triggerOptions}
                    value={displayType}
                    placeholder="Select trigger type"
                    onChange={(value) => {
                        value === 'event'
                            ? setWorkflowActionConfig(node.id, { type: 'event', filters: {} })
                            : value === 'survey'
                              ? setWorkflowActionConfig(node.id, {
                                    type: 'event',
                                    filters: {
                                        events: [{ id: SurveyEventName.SENT, type: 'events', name: 'Survey sent' }],
                                        properties: [],
                                    },
                                })
                              : value === 'webhook'
                                ? setWorkflowActionConfig(node.id, {
                                      type: 'webhook',
                                      template_id: 'template-source-webhook',
                                      inputs: {},
                                  })
                                : value === 'manual'
                                  ? setWorkflowActionConfig(node.id, {
                                        type: 'manual',
                                        template_id: 'template-source-webhook',
                                        inputs: {
                                            event: {
                                                order: 0,
                                                value: '$workflow_triggered',
                                            },
                                            distinct_id: {
                                                order: 1,
                                                value: '{request.body.user_id}',
                                            },
                                            method: {
                                                order: 2,
                                                value: 'POST',
                                            },
                                        },
                                    })
                                  : value === 'schedule'
                                    ? setWorkflowActionConfig(node.id, {
                                          type: 'schedule',
                                          template_id: 'template-source-webhook',
                                          inputs: {
                                              event: {
                                                  order: 0,
                                                  value: '$workflow_triggered',
                                              },
                                              distinct_id: {
                                                  order: 1,
                                                  value: '{request.body.user_id}',
                                              },
                                              method: {
                                                  order: 2,
                                                  value: 'POST',
                                              },
                                          },
                                          scheduled_at: undefined,
                                      })
                                    : value === 'batch'
                                      ? setWorkflowActionConfig(node.id, {
                                            type: 'batch',
                                            filters: {
                                                properties: [],
                                            },
                                            scheduled_at: undefined,
                                        })
                                      : value === 'tracking_pixel'
                                        ? setWorkflowActionConfig(node.id, {
                                              type: 'tracking_pixel',
                                              template_id: 'template-source-webhook-pixel',
                                              inputs: {},
                                          })
                                        : null
                    }}
                />
            </LemonField.Pure>
            {isSurveyTriggerConfig(node.data.config) ? (
                <StepTriggerConfigurationSurvey
                    action={node.data}
                    config={node.data.config as Extract<HogFlowAction['config'], { type: 'event' }>}
                />
            ) : node.data.config.type === 'event' ? (
                <StepTriggerConfigurationEvents action={node.data} config={node.data.config} />
            ) : node.data.config.type === 'webhook' ? (
                <StepTriggerConfigurationWebhook action={node.data} config={node.data.config} />
            ) : node.data.config.type === 'manual' ? (
                <StepTriggerConfigurationManual />
            ) : node.data.config.type === 'schedule' ? (
                <StepTriggerConfigurationSchedule action={node.data} config={node.data.config} />
            ) : node.data.config.type === 'batch' ? (
                <StepTriggerConfigurationBatch action={node.data} config={node.data.config} />
            ) : node.data.config.type === 'tracking_pixel' ? (
                <StepTriggerConfigurationTrackingPixel action={node.data} config={node.data.config} />
            ) : null}
        </div>
    )
}

function StepTriggerConfigurationEvents({
    action,
    config,
}: {
    action: Extract<HogFlowAction, { type: 'trigger' }>
    config: Extract<HogFlowAction['config'], { type: 'event' }>
}): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const validationResult = actionValidationErrorsById[action.id]
    const filterTestAccounts = config.filters?.filter_test_accounts ?? false

    return (
        <>
            <div className="flex flex-col">
                <p className="mb-0">Choose which events or actions will enter a user into the workflow.</p>
            </div>

            <LemonField.Pure error={validationResult?.errors?.filters}>
                <HogFlowEventFilters
                    filters={config.filters ?? {}}
                    setFilters={(filters) =>
                        setWorkflowActionConfig(action.id, {
                            type: 'event',
                            filters: { ...filters, filter_test_accounts: filterTestAccounts },
                        })
                    }
                    filtersKey={`workflow-trigger-${action.id}`}
                    typeKey="workflow-trigger"
                    buttonCopy="Add trigger event"
                />
            </LemonField.Pure>

            <TestAccountFilter
                filters={{ filter_test_accounts: filterTestAccounts }}
                onChange={({ filter_test_accounts }) =>
                    setWorkflowActionConfig(action.id, {
                        type: 'event',
                        filters: { ...config.filters, filter_test_accounts },
                    })
                }
            />

            <LemonDivider />
            <FrequencySection />
            <LemonDivider />
            <ConversionGoalSection />
            <LemonDivider />
            <ExitConditionSection />
        </>
    )
}

function StepTriggerConfigurationSurvey({
    action,
    config,
}: {
    action: Extract<HogFlowAction, { type: 'trigger' }>
    config: Extract<HogFlowAction['config'], { type: 'event' }>
}): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { allSurveys, surveysLoading, moreSurveysLoading, hasMoreSurveys, responseCounts } =
        useValues(surveyTriggerLogic)
    const { loadSurveys, loadMoreSurveys } = useActions(surveyTriggerLogic)
    const selectedSurveyId = getSelectedSurveyId(config)
    const filterTestAccounts = config.filters?.filter_test_accounts ?? false

    // Search state for filtering surveys
    const [searchTerm, setSearchTerm] = useState('')

    // Store selected survey name so it persists even when survey list hasn't loaded
    const [selectedSurveyName, setSelectedSurveyName] = useState<string | null>(null)

    useEffect(() => {
        loadSurveys()
    }, [loadSurveys])

    // Update stored name when survey is found in the list
    useEffect(() => {
        if (selectedSurveyId) {
            const survey = allSurveys.find((s) => s.id === selectedSurveyId)
            if (survey) {
                setSelectedSurveyName(survey.name)
            }
        } else {
            setSelectedSurveyName(null)
        }
    }, [selectedSurveyId, allSurveys])

    // Filter surveys based on search term
    const filteredSurveys = useMemo(() => {
        if (!searchTerm) {
            return allSurveys
        }
        const lower = searchTerm.toLowerCase()
        return allSurveys.filter((s) => s.name.toLowerCase().includes(lower))
    }, [allSurveys, searchTerm])

    // Determine the label to show for the selected survey
    const selectedSurveyLabel = selectedSurveyName ?? (selectedSurveyId ? 'Loading...' : null)

    // Build options - always include a fallback for the selected survey at the start
    const surveyOptions = [
        // Always include selected survey option first so LemonSelect can find its label
        ...(selectedSurveyId && selectedSurveyLabel
            ? [
                  {
                      label: selectedSurveyLabel,
                      value: selectedSurveyId,
                      hidden: true, // Mark as hidden - we'll filter it from display
                  },
              ]
            : []),
        // Search input as first visible option
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
                        // Allow Escape to bubble up so the menu can close
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
            value: null as string | null,
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
                            return // Ignore search input selection
                        }
                        if (surveyId === '__load_more__') {
                            loadMoreSurveys()
                            return
                        }
                        setSearchTerm('') // Clear search on selection
                        const properties = surveyId
                            ? [{ key: '$survey_id', value: surveyId, operator: 'exact', type: 'event' }]
                            : []
                        setWorkflowActionConfig(action.id, {
                            type: 'event',
                            filters: {
                                events: [{ id: SurveyEventName.SENT, type: 'events', name: 'Survey sent' }],
                                properties,
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

            {(() => {
                // Warning: "Any survey" selected but no surveys exist
                if (selectedSurveyId === null && !surveysLoading && allSurveys.length === 0) {
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

                // Warning: Selected survey is not active
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
                    setWorkflowActionConfig(action.id, {
                        type: 'event',
                        filters: { ...config.filters, filter_test_accounts },
                    })
                }
            />

            <LemonDivider />
            <FrequencySection />
            <LemonDivider />
            <ConversionGoalSection />
            <LemonDivider />
            <ExitConditionSection />
        </>
    )
}

function StepTriggerConfigurationWebhook({
    action,
    config,
}: {
    action: Extract<HogFlowAction, { type: 'trigger' }>
    config: Extract<HogFlowAction['config'], { type: 'webhook' }>
}): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { workflow, actionValidationErrorsById } = useValues(workflowLogic)
    const validationResult = actionValidationErrorsById[action.id]

    const webhookUrl = workflow.id === 'new' ? null : publicWebhooksHostOrigin() + '/public/webhooks/' + workflow.id

    return (
        <>
            <LemonCollapse
                className="shrink-0"
                defaultActiveKey="instructions"
                panels={[
                    {
                        key: 'instructions',
                        header: 'Usage instructions',
                        className: 'p-3 bg-surface-secondary flex flex-col gap-2',
                        content: (
                            <>
                                {!webhookUrl ? (
                                    <div className="text-xs text-muted italic border rounded p-1 bg-surface-primary">
                                        The webhook URL will be shown here once you save the workflow
                                    </div>
                                ) : (
                                    <CodeSnippet thing="Webhook URL">{webhookUrl}</CodeSnippet>
                                )}

                                <div className="text-sm">
                                    The webhook can be called with any JSON payload. You can then use the configuration
                                    options to parse the <code>request.body</code> or <code>request.headers</code> to
                                    map to the required fields.
                                </div>
                            </>
                        ),
                    },
                ]}
            />
            <HogFlowFunctionConfiguration
                templateId={config.template_id}
                inputs={config.inputs}
                setInputs={(inputs) =>
                    setWorkflowActionConfig(action.id, {
                        type: 'webhook',
                        inputs,
                        template_id: config.template_id,
                        template_uuid: config.template_uuid,
                    })
                }
                errors={validationResult?.errors}
            />
        </>
    )
}

function StepTriggerConfigurationManual(): JSX.Element {
    return (
        <>
            <div className="flex gap-1">
                <p className="mb-0">
                    This workflow can be triggered manually via{' '}
                    <Tooltip title="It's up there on the top right ⤴︎">
                        <span className="font-bold cursor-pointer">the trigger button</span>
                    </Tooltip>
                    .
                </p>
            </div>
        </>
    )
}

function StepTriggerConfigurationSchedule({
    action,
    config,
}: {
    action: Extract<HogFlowAction, { type: 'trigger' }>
    config: Extract<HogFlowAction['config'], { type: 'schedule' }>
}): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const validationResult = actionValidationErrorsById[action.id]

    const scheduledDateTime = config.scheduled_at ? dayjs(config.scheduled_at) : null

    return (
        <>
            <div className="flex flex-col gap-2">
                <p className="mb-0">Schedule this workflow to run at a specific time in the future.</p>
                <LemonField.Pure label="Scheduled time" error={validationResult?.errors?.scheduled_at}>
                    <div className="flex flex-col gap-2">
                        <LemonCalendarSelectInput
                            value={scheduledDateTime}
                            onChange={(date) => {
                                setWorkflowActionConfig(action.id, {
                                    type: 'schedule',
                                    template_id: config.template_id,
                                    template_uuid: config.template_uuid,
                                    inputs: config.inputs,
                                    scheduled_at: date ? date.toISOString() : undefined,
                                })
                            }}
                            granularity="minute"
                            selectionPeriod="upcoming"
                            showTimeToggle={false}
                        />
                        {scheduledDateTime && (
                            <div className="text-xs text-muted">
                                Timezone: {dayjs.tz.guess()} • Scheduled for:{' '}
                                {scheduledDateTime.format('MMMM D, YYYY [at] h:mm A')}
                            </div>
                        )}
                    </div>
                </LemonField.Pure>
            </div>
        </>
    )
}

function StepTriggerAffectedUsers({ actionId, filters }: { actionId: string; filters: any }): JSX.Element | null {
    const logic = batchTriggerLogic({ id: actionId, filters })
    const { blastRadiusLoading, blastRadius } = useValues(logic)

    if (blastRadiusLoading) {
        return <Spinner />
    }

    if (!blastRadius) {
        return null
    }

    const { users_affected, total_users } = blastRadius

    if (users_affected != null && total_users != null) {
        return (
            <div className="text-muted">
                approximately {humanFriendlyNumber(users_affected)} of {humanFriendlyNumber(total_users)} persons.
            </div>
        )
    }

    return null
}

function StepTriggerConfigurationBatch({
    action,
    config,
}: {
    action: Extract<HogFlowAction, { type: 'trigger' }>
    config: Extract<HogFlowAction['config'], { type: 'batch' }>
}): JSX.Element {
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const validationResult = actionValidationErrorsById[action.id]

    const scheduledDateTime = config.scheduled_at ? dayjs(config.scheduled_at) : null

    return (
        <div className="flex flex-col gap-2 my-2">
            <div className="flex gap-1">
                <span className="font-semibold">This batch will include</span>{' '}
                <StepTriggerAffectedUsers actionId={action.id} filters={config.filters} />
            </div>
            <div>
                <PropertyFilters
                    pageKey={`workflows-batch-trigger-property-filters-${action.id}`}
                    propertyFilters={config.filters.properties}
                    addText="Add condition"
                    orFiltering
                    sendAllKeyUpdates
                    allowRelativeDateOptions
                    exactMatchFeatureFlagCohortOperators
                    hideBehavioralCohorts
                    logicalRowDivider
                    onChange={(properties) =>
                        partialSetWorkflowActionConfig(action.id, {
                            filters: {
                                properties,
                            },
                        })
                    }
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.FeatureFlags,
                        TaxonomicFilterGroupType.Metadata,
                    ]}
                    taxonomicFilterOptionsFromProp={{
                        [TaxonomicFilterGroupType.Metadata]: [
                            { name: 'distinct_id', propertyFilterType: PropertyFilterType.Person },
                        ],
                    }}
                    hasRowOperator={false}
                />
            </div>
            <LemonDivider />
            <div className="flex gap-2">
                <span className="font-semibold">Schedule for later?</span>
                <LemonCheckbox
                    checked={Boolean(config.scheduled_at)}
                    onChange={(checked) =>
                        partialSetWorkflowActionConfig(action.id, {
                            scheduled_at: checked ? dayjs().add(5, 'minutes').toISOString() : undefined,
                        })
                    }
                />
            </div>
            {config.scheduled_at && (
                <LemonField.Pure label="Scheduled time" error={validationResult?.errors?.scheduled_at}>
                    <div className="flex flex-col gap-2">
                        <LemonCalendarSelectInput
                            value={scheduledDateTime}
                            onChange={(date) => {
                                partialSetWorkflowActionConfig(action.id, {
                                    scheduled_at: date ? date.toISOString() : undefined,
                                })
                            }}
                            granularity="minute"
                            selectionPeriod="upcoming"
                            showTimeToggle={false}
                        />
                        {scheduledDateTime && (
                            <div className="text-xs text-muted">
                                Timezone: {dayjs.tz.guess()} • Scheduled for:{' '}
                                {scheduledDateTime.format('MMMM D, YYYY [at] h:mm A')}
                            </div>
                        )}
                    </div>
                </LemonField.Pure>
            )}
        </div>
    )
}

function StepTriggerConfigurationTrackingPixel({
    action,
    config,
}: {
    action: Extract<HogFlowAction, { type: 'trigger' }>
    config: Extract<HogFlowAction['config'], { type: 'tracking_pixel' }>
}): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { workflow, actionValidationErrorsById } = useValues(workflowLogic)
    const validationResult = actionValidationErrorsById[action.id]

    const trackingPixelUrl =
        workflow.id !== 'new' ? `${publicWebhooksHostOrigin()}/public/webhooks/${workflow.id}` : null

    const trackingPixelHtml = trackingPixelUrl
        ? `<img
    src="${trackingPixelUrl}.gif"
    width="1" height="1" style="display:none;" alt=""
/>`
        : null

    return (
        <>
            <LemonCollapse
                className="shrink-0"
                defaultActiveKey="instructions"
                panels={[
                    {
                        key: 'instructions',
                        header: 'Usage instructions',
                        className: 'p-3 bg-surface-secondary flex flex-col gap-2',
                        content: (
                            <>
                                {!trackingPixelUrl ? (
                                    <div className="text-xs text-muted italic border rounded p-1 bg-surface-primary">
                                        The tracking pixel URL will be shown here once you save the workflow
                                    </div>
                                ) : (
                                    <CodeSnippet thing="Tracking pixel URL">{trackingPixelUrl}</CodeSnippet>
                                )}

                                <div className="text-sm">
                                    The tracking pixel can be called with a GET request to the URL above. You can embed
                                    it as an image or call it with an HTTP request in any other way.
                                </div>

                                {trackingPixelUrl && (
                                    <CodeSnippet thing="Tracking pixel HTML">{trackingPixelHtml}</CodeSnippet>
                                )}

                                <div>
                                    You can use query parameters to pass in data that you can parse into the event
                                    properties below, or you can hard code the values. This will not create a PostHog
                                    event by default, it will only be used to trigger the workflow.
                                </div>
                            </>
                        ),
                    },
                ]}
            />

            <HogFlowFunctionConfiguration
                templateId={config.template_id}
                inputs={config.inputs}
                setInputs={(inputs) =>
                    setWorkflowActionConfig(action.id, {
                        type: 'tracking_pixel',
                        inputs,
                        template_id: config.template_id,
                        template_uuid: config.template_uuid,
                    })
                }
                errors={validationResult?.errors}
            />
        </>
    )
}

const FREQUENCY_OPTIONS = [
    { value: null, label: 'Every time the trigger fires' },
    { value: '{person.id}', label: 'One time' },
]

const TTL_OPTIONS = [
    { value: null, label: 'indefinitely' },
    { value: 5 * 60, label: '5 minutes' },
    { value: 15 * 60, label: '15 minutes' },
    { value: 30 * 60, label: '30 minutes' },
    { value: 60 * 60, label: '1 hour' },
    { value: 2 * 60 * 60, label: '2 hours' },
    { value: 4 * 60 * 60, label: '4 hours' },
    { value: 8 * 60 * 60, label: '8 hours' },
    { value: 12 * 60 * 60, label: '12 hours' },
    { value: 24 * 60 * 60, label: '24 hours' },
    { value: 24 * 60 * 60 * 7, label: '7 days' },
    { value: 24 * 60 * 60 * 30, label: '30 days' },
    { value: 24 * 60 * 60 * 90, label: '90 days' },
    { value: 24 * 60 * 60 * 180, label: '180 days' },
    { value: 24 * 60 * 60 * 365, label: '365 days' },
]

function TTLSelect({
    value,
    onChange,
}: {
    value: number | null | undefined
    onChange: (val: number | null) => void
}): JSX.Element {
    return (
        <div className="flex flex-wrap gap-1 items-center">
            <span>per</span>
            <LemonSelect value={value} onChange={onChange} options={TTL_OPTIONS} />
        </div>
    )
}

function FrequencySection(): JSX.Element {
    const { setWorkflowValue } = useActions(workflowLogic)
    const { workflow } = useValues(workflowLogic)

    return (
        <div className="flex flex-col w-full py-2">
            <span className="flex gap-1">
                <IconClock className="text-lg" />
                <span className="text-md font-semibold">Frequency</span>
            </span>
            <p>Limit how often users can enter this workflow</p>

            <LemonField.Pure>
                <div className="flex flex-wrap gap-1 items-center">
                    <LemonSelect
                        options={FREQUENCY_OPTIONS}
                        value={workflow.trigger_masking?.hash ?? null}
                        onChange={(val) =>
                            setWorkflowValue(
                                'trigger_masking',
                                val
                                    ? {
                                          hash: val,
                                          ttl: workflow.trigger_masking?.ttl ?? 60 * 30,
                                      }
                                    : null
                            )
                        }
                    />
                    {workflow.trigger_masking?.hash ? (
                        <TTLSelect
                            value={workflow.trigger_masking.ttl}
                            onChange={(val) =>
                                setWorkflowValue('trigger_masking', { ...workflow.trigger_masking, ttl: val })
                            }
                        />
                    ) : null}
                </div>
            </LemonField.Pure>
        </div>
    )
}

function ConversionGoalSection(): JSX.Element {
    const { setWorkflowValue } = useActions(workflowLogic)
    const { workflow } = useValues(workflowLogic)

    return (
        <div className="flex flex-col py-2 w-full">
            <span className="flex gap-1">
                <IconTarget className="text-lg" />
                <span className="text-md font-semibold">Conversion goal (optional)</span>
            </span>
            <p>Define what a user must do to be considered converted.</p>

            <div className="flex gap-1 max-w-240">
                <div className="flex flex-col flex-2 gap-4">
                    <LemonField.Pure label="Detect conversion from property changes">
                        <PropertyFilters
                            buttonText="Add property conversion"
                            propertyFilters={workflow.conversion?.filters ?? []}
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.PersonProperties,
                                TaxonomicFilterGroupType.Cohorts,
                                TaxonomicFilterGroupType.HogQLExpression,
                            ]}
                            onChange={(filters) => setWorkflowValue('conversion', { ...workflow.conversion, filters })}
                            pageKey="workflow-conversion-properties"
                            hideBehavioralCohorts
                        />
                    </LemonField.Pure>
                    <div className="flex flex-col gap-1">
                        <LemonLabel>
                            Detect conversion from events
                            <LemonTag>Coming soon</LemonTag>
                        </LemonLabel>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlusSmall />}
                            onClick={() => {
                                posthog.capture('workflows workflow event conversion clicked')
                                lemonToast.info('Event targeting coming soon!')
                            }}
                        >
                            Add event conversion
                        </LemonButton>
                    </div>
                </div>
                <LemonDivider vertical />
                <div className="flex-1">
                    <LemonField.Pure
                        label="Conversion window"
                        info="How long after entering the workflow should we check for conversion? After this window, users will be considered for conversion."
                    >
                        <LemonSelect
                            value={workflow.conversion?.window_minutes}
                            onChange={(value) =>
                                setWorkflowValue('conversion', {
                                    ...workflow.conversion,
                                    window_minutes: value,
                                })
                            }
                            placeholder="No conversion window"
                            allowClear
                            options={[
                                { value: 24 * 60 * 60, label: '24 hours' },
                                { value: 7 * 24 * 60 * 60, label: '7 days' },
                                { value: 14 * 24 * 60 * 60, label: '14 days' },
                                { value: 30 * 24 * 60 * 60, label: '30 days' },
                            ]}
                        />
                    </LemonField.Pure>
                </div>
            </div>
        </div>
    )
}

function ExitConditionSection(): JSX.Element {
    const { setWorkflowValue } = useActions(workflowLogic)
    const { workflow } = useValues(workflowLogic)

    return (
        <div className="flex flex-col flex-1 w-full py-2">
            <span className="flex gap-1">
                <IconLeave className="text-lg" />
                <span className="text-md font-semibold">Exit condition</span>
            </span>
            <p>Choose how your users move through the workflow.</p>

            <LemonField.Pure>
                <LemonRadio
                    value={workflow.exit_condition ?? 'exit_only_at_end'}
                    onChange={(value) => setWorkflowValue('exit_condition', value)}
                    options={[
                        {
                            value: 'exit_only_at_end',
                            label: 'Exit only once workflow reaches the end',
                        },
                        {
                            value: 'exit_on_trigger_not_matched',
                            label: 'Exit when trigger filters no longer match',
                        },
                        {
                            value: 'exit_on_conversion',
                            label: 'Exit when conversion goal is met',
                        },
                        {
                            value: 'exit_on_trigger_not_matched_or_conversion',
                            label: 'Exit when trigger filters no longer match, or when conversion goal is met',
                        },
                    ]}
                />
            </LemonField.Pure>
        </div>
    )
}
