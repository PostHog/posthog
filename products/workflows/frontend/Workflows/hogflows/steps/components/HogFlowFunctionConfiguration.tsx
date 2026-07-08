import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { IconCheck } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, Link, Spinner } from '@posthog/lemon-ui'

import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { templateToConfiguration } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { CyclotronJobInputType, HogFunctionMappingType } from '~/types'

import { workflowLogic } from '../../../workflowLogic'
import { HogFlowFunctionMappings } from './HogFlowFunctionMappings'

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
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const template = hogFunctionTemplatesById[templateId]
    const isEmailStep = templateId === 'template-email'
    const isPushStep = templateId === 'template-native-push'
    const engagementEventsAvailable = !!featureFlags[FEATURE_FLAGS.WORKFLOWS_ENGAGEMENT_EVENTS]
    const engagementEventsEnabled = !!currentTeam?.workflows_config?.capture_workflows_engagement_events
    useEffect(() => {
        // oxlint-disable-next-line exhaustive-deps
        if (template) {
            const defaults = templateToConfiguration(template).inputs ?? {}
            const currentInputs = inputs ?? {}
            const hasMissingDefaults = Object.keys(defaults).some((key) => !(key in currentInputs))
            if (hasMissingDefaults) {
                setInputs({ ...defaults, ...currentInputs })
            }
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
        return <TemplateNotFoundFallback templateId={templateId} />
    }

    const triggerType = workflow?.trigger?.type

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
            } else if (variable.type === 'dictionary' || variable.type === 'json') {
                workflowVariables[variable.key] = {}
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
        // Event-based triggers
        sampleGlobals.event = {
            event: 'example_event',
            distinct_id: 'user123',
            properties: {
                $current_url: 'https://example.com',
            },
            timestamp: '2024-01-01T12:00:00Z',
        }
        sampleGlobals.person = {
            id: 'person123',
            properties: {
                email: 'user@example.com',
                name: 'John Doe',
            },
        }
        sampleGlobals.groups = {}
    } else if (triggerType === 'batch') {
        sampleGlobals.person = {
            id: 'person123',
            properties: {
                email: 'user@example.com',
                name: 'John Doe',
            },
        }
    }

    // Native push carries a long tail of optional Android/iOS override fields. Keep the core message
    // fields inline and tuck the platform-specific ones into collapsed sections so the form stays flat.
    const inputsSchema = template.inputs_schema ?? []
    const isPlatformInput = (key: string): boolean => key.startsWith('android_') || key.startsWith('ios_')
    const coreInputsSchema = isPushStep ? inputsSchema.filter((s) => !isPlatformInput(s.key)) : inputsSchema
    const androidInputsSchema = isPushStep ? inputsSchema.filter((s) => s.key.startsWith('android_')) : []
    const iosInputsSchema = isPushStep ? inputsSchema.filter((s) => s.key.startsWith('ios_')) : []

    const renderInputs = (schema: typeof inputsSchema): JSX.Element => (
        <CyclotronJobInputs
            errors={errors}
            configuration={{ inputs: inputs as Record<string, CyclotronJobInputType>, inputs_schema: schema }}
            showSource={false}
            sampleGlobalsWithInputs={sampleGlobals}
            onInputChange={(key, value) => setInputs({ ...inputs, [key]: value })}
        />
    )

    return (
        <>
            {renderInputs(coreInputsSchema)}
            {isPushStep && (androidInputsSchema.length > 0 || iosInputsSchema.length > 0) && (
                <LemonCollapse
                    className="mt-2"
                    multiple
                    panels={[
                        ...(androidInputsSchema.length > 0
                            ? [
                                  {
                                      key: 'android',
                                      header: 'Android options',
                                      content: renderInputs(androidInputsSchema),
                                  },
                              ]
                            : []),
                        ...(iosInputsSchema.length > 0
                            ? [{ key: 'ios', header: 'iOS options', content: renderInputs(iosInputsSchema) }]
                            : []),
                    ]}
                />
            )}
            {isEmailStep && engagementEventsAvailable ? (
                engagementEventsEnabled ? (
                    <div className="flex items-center gap-1.5 mt-2 text-xs text-muted-alt">
                        <IconCheck className="text-success text-base" />
                        <span>Email engagement is being captured as PostHog events.</span>
                        <Link
                            to={urls.settings('environment-workflows', 'workflows-engagement-events')}
                            target="_blank"
                        >
                            Manage in settings
                        </Link>
                    </div>
                ) : (
                    <LemonBanner type="info" hideIcon className="mt-2">
                        <div className="flex flex-col gap-2">
                            <span className="text-xs">
                                Email engagement (sends, opens, clicks, bounces) is recorded as workflow metrics. You
                                can also capture these as standard PostHog events for use in insights and funnels. They
                                count toward your event usage and are billed like any other event.
                            </span>
                            <div className="flex items-center gap-2">
                                <LemonButton
                                    type="primary"
                                    size="xsmall"
                                    loading={currentTeamLoading}
                                    onClick={() =>
                                        updateCurrentTeam({
                                            workflows_config: {
                                                ...currentTeam?.workflows_config,
                                                capture_workflows_engagement_events: true,
                                            },
                                        })
                                    }
                                >
                                    Enable engagement events
                                </LemonButton>
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    to={urls.settings('environment-workflows', 'workflows-engagement-events')}
                                    targetBlank
                                >
                                    Manage in settings
                                </LemonButton>
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    to="https://posthog.com/docs/workflows/engagement-events"
                                    targetBlank
                                >
                                    Learn more
                                </LemonButton>
                            </div>
                        </div>
                    </LemonBanner>
                )
            ) : null}
            <HogFlowFunctionMappings
                useMapping={!isPushStep && (Array.isArray(mappings) || (template?.mapping_templates?.length ?? 0) > 0)}
                inputs={inputs}
                inputs_schema={template?.inputs_schema ?? []}
                mappings={mappings ?? []}
                mappingTemplates={template?.mapping_templates ?? []}
                onChange={(mappings) => setMappings?.(mappings)}
            />
        </>
    )
}

// Reaching this fallback means the workflow editor finished loading the template list but the
// referenced template was not in it — typically a server-side filter regression (see PR #61992)
// or a workflow that points at a deleted/renamed template. Surfaces to error tracking so an
// alert can fire before users start reporting it.
function TemplateNotFoundFallback({ templateId }: { templateId: string }): JSX.Element {
    useEffect(() => {
        posthog.captureException(new Error('Workflow editor: hog function template not found'), {
            severity: 'error',
            tag: 'workflow_editor_template_not_found',
            templateId,
        })
    }, [templateId])
    return <div>Template not found!</div>
}
