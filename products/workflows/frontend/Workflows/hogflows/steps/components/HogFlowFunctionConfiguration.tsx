import { useValues } from 'kea'
import { useEffect } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { templateToConfiguration } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'

import { CyclotronJobInputType, HogFunctionMappingType, SurveyQuestionType } from '~/types'

import { workflowLogic } from '../../../workflowLogic'
import { surveyTriggerLogic } from '../surveyTriggerLogic'
import { HogFlowFunctionMappings } from './HogFlowFunctionMappings'

function getSampleValueForQuestionType(type: string): any {
    switch (type) {
        case SurveyQuestionType.Open:
            return 'User response text'
        case SurveyQuestionType.Rating:
            return '8'
        case SurveyQuestionType.SingleChoice:
            return 'Selected option'
        case SurveyQuestionType.MultipleChoice:
            return ['Option A', 'Option B']
        case SurveyQuestionType.Link:
            return null
        default:
            return 'response'
    }
}

export function HogFlowFunctionConfiguration({
    templateId,
    inputs,
    setInputs,
    mappings,
    setMappings,
    errors,
}: {
    templateId: string
    inputs: Record<string, CyclotronJobInputType>
    mappings?: HogFunctionMappingType[]
    setInputs: (inputs: Record<string, CyclotronJobInputType>) => void
    setMappings?: (mappings: HogFunctionMappingType[]) => void
    errors?: Record<string, string>
}): JSX.Element {
    const { workflow, hogFunctionTemplatesById, hogFunctionTemplatesByIdLoading } = useValues(workflowLogic)
    const { allSurveys } = useValues(surveyTriggerLogic)

    const template = hogFunctionTemplatesById[templateId]
    useEffect(() => {
        // oxlint-disable-next-line exhaustive-deps
        if (template && Object.keys(inputs ?? {}).length === 0) {
            setInputs(templateToConfiguration(template).inputs ?? {})
        }
    }, [templateId])

    if (hogFunctionTemplatesByIdLoading) {
        return (
            <div className="flex justify-center items-center">
                <Spinner />
            </div>
        )
    }

    if (!template) {
        return <div>Template not found!</div>
    }

    const triggerType = workflow?.trigger?.type

    // Detect if the trigger is a survey trigger
    const triggerEvents =
        triggerType === 'event' && workflow?.trigger && 'filters' in workflow.trigger
            ? (workflow.trigger.filters?.events ?? [])
            : []
    const isSurveyTrigger = triggerEvents.some((e: any) => e.id === 'survey sent')

    // If a specific survey is selected, find it for question-aware autocomplete
    const surveyIdProp =
        isSurveyTrigger && workflow?.trigger && 'filters' in workflow.trigger
            ? workflow.trigger.filters?.properties?.find((p: any) => p.key === '$survey_id' && p.operator === 'exact')
            : null
    const selectedSurvey = surveyIdProp ? allSurveys.find((s) => s.id === surveyIdProp.value) : null

    // Build workflow variables object for autocomplete
    const workflowVariables: Record<string, any> = {}
    if (workflow?.variables) {
        workflow.variables.forEach((variable) => {
            // Use placeholder values based on variable type
            if (variable.type === 'string') {
                workflowVariables[variable.key] = 'example_value'
            } else if (variable.type === 'number') {
                workflowVariables[variable.key] = 123
            } else if (variable.type === 'boolean') {
                workflowVariables[variable.key] = true
            } else {
                workflowVariables[variable.key] = null
            }
        })
    }

    const sampleGlobals: Record<string, any> = {
        variables: workflowVariables,
    }

    if (triggerType === 'webhook') {
        sampleGlobals.request = {
            method: 'POST',
            headers: {},
            body: {},
            params: {},
        }
    } else if (triggerType === 'event') {
        if (isSurveyTrigger) {
            // Properties matching the actual posthog-js SDK survey sent event schema
            const surveyProperties: Record<string, any> = {
                $survey_id: selectedSurvey?.id ?? 'survey-uuid',
                $survey_name: selectedSurvey?.name ?? 'Survey name',
                $survey_completed: true,
                $survey_submission_id: 'submission-uuid',
                $survey_iteration: null,
                $survey_iteration_start_date: null,
                $survey_questions: [{ id: 'question-id', question: 'Question text', response: 'Response' }],
            }

            if (selectedSurvey?.questions) {
                // Per-question response fields keyed by question ID
                selectedSurvey.questions.forEach((question) => {
                    if (question.type === SurveyQuestionType.Link) {
                        return // Link questions don't capture responses
                    }
                    if (question.id) {
                        surveyProperties[`$survey_response_${question.id}`] = getSampleValueForQuestionType(
                            question.type
                        )
                    }
                })
                // $survey_questions contains objects with {id, question, response}
                surveyProperties.$survey_questions = selectedSurvey.questions.map((q) => ({
                    id: q.id ?? '',
                    question: q.question,
                    response: getSampleValueForQuestionType(q.type),
                }))
            }

            sampleGlobals.event = {
                event: 'survey sent',
                distinct_id: 'user123',
                properties: surveyProperties,
                timestamp: '2024-01-01T12:00:00Z',
            }
        } else {
            sampleGlobals.event = {
                event: 'example_event',
                distinct_id: 'user123',
                properties: {
                    $current_url: 'https://example.com',
                },
                timestamp: '2024-01-01T12:00:00Z',
            }
        }
        sampleGlobals.person = {
            id: 'person123',
            properties: {
                email: 'user@example.com',
                name: 'John Doe',
            },
        }
        sampleGlobals.groups = {}
    }

    return (
        <>
            <CyclotronJobInputs
                errors={errors}
                configuration={{
                    inputs: inputs as Record<string, CyclotronJobInputType>,
                    inputs_schema: template?.inputs_schema ?? [],
                }}
                showSource={false}
                sampleGlobalsWithInputs={sampleGlobals}
                onInputChange={(key, value) => setInputs({ ...inputs, [key]: value })}
            />
            <HogFlowFunctionMappings
                useMapping={Array.isArray(mappings) ?? (template?.mapping_templates?.length ?? 0) > 0}
                inputs={inputs}
                inputs_schema={template?.inputs_schema ?? []}
                mappings={mappings ?? []}
                mappingTemplates={template?.mapping_templates ?? []}
                onChange={(mappings) => setMappings?.(mappings)}
            />
        </>
    )
}
