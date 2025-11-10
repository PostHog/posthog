import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconBolt, IconButton, IconClock, IconLeave, IconPlusSmall, IconTarget, IconWebhooks } from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonDivider,
    LemonLabel,
    LemonSelect,
    LemonTag,
    Tooltip,
    lemonToast,
} from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { IconAdsClick } from 'lib/lemon-ui/icons'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowEventFilters } from '../filters/HogFlowFilters'
import { HogFlowAction } from '../types'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'

export function StepTriggerConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'trigger' }>>
}): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)

    const type = node.data.config.type
    const validationResult = actionValidationErrorsById[node.id]

    return (
        <div className="flex flex-col items-start w-full gap-2">
            <span className="flex gap-1">
                <IconBolt className="text-lg" />
                <span className="text-md font-semibold">Trigger type</span>
            </span>
            <span>What causes this workflow to begin?</span>
            <LemonField.Pure error={validationResult?.errors?.type}>
                <LemonSelect
                    options={[
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
                                    <p className="text-xs text-muted">
                                        Trigger your workflow using an incoming HTTP webhook
                                    </p>
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
                                    <p className="text-xs text-muted">
                                        Trigger your workflow manually... with a button!
                                    </p>
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
                                    <p className="text-xs text-muted">
                                        Trigger your workflow using a 1x1 tracking pixel
                                    </p>
                                </div>
                            ),
                        },
                    ]}
                    value={type}
                    placeholder="Select trigger type"
                    onChange={(value) => {
                        value === 'event'
                            ? setWorkflowActionConfig(node.id, { type: 'event', filters: {} })
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
            {node.data.config.type === 'event' ? (
                <StepTriggerConfigurationEvents action={node.data} config={node.data.config} />
            ) : node.data.config.type === 'webhook' ? (
                <StepTriggerConfigurationWebhook action={node.data} config={node.data.config} />
            ) : node.data.config.type === 'manual' ? (
                <StepTriggerConfigurationManual />
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

    return (
        <>
            <div className="flex flex-col">
                <p className="mb-0">Choose which events or actions will enter a user into the workflow.</p>
            </div>

            <LemonField.Pure error={validationResult?.errors?.filters}>
                <HogFlowEventFilters
                    filters={config.filters ?? {}}
                    setFilters={(filters) =>
                        setWorkflowActionConfig(action.id, { type: 'event', filters: filters ?? {} })
                    }
                    typeKey="workflow-trigger"
                    buttonCopy="Add trigger event"
                />
            </LemonField.Pure>

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
                        <span className="font-bold cursor-pointer">the trigger button on the top</span>
                    </Tooltip>
                </p>
            </div>
        </>
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
