import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconBolt, IconPlusSmall, IconWebhooks } from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonDivider,
    LemonLabel,
    LemonSelect,
    LemonTag,
    lemonToast,
} from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { IconAdsClick } from 'lib/lemon-ui/icons'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'

import { campaignLogic } from '../../campaignLogic'
import { HogFlowEventFilters } from '../filters/HogFlowFilters'
import { HogFlowAction } from '../types'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'

export function StepTriggerConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'trigger' }>>
}): JSX.Element {
    const { setCampaignActionConfig } = useActions(campaignLogic)
    const { actionValidationErrorsById } = useValues(campaignLogic)

    const type = node.data.config.type
    const validationResult = actionValidationErrorsById[node.id]

    return (
        <>
            <LemonField.Pure label="Trigger type" error={validationResult?.errors?.type}>
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
                            ? setCampaignActionConfig(node.id, { type: 'event', filters: {} })
                            : value === 'webhook'
                              ? setCampaignActionConfig(node.id, {
                                    type: 'webhook',
                                    template_id: 'template-source-webhook',
                                    inputs: {},
                                })
                              : value === 'tracking_pixel'
                                ? setCampaignActionConfig(node.id, {
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
            ) : node.data.config.type === 'tracking_pixel' ? (
                <StepTriggerConfigurationTrackingPixel action={node.data} config={node.data.config} />
            ) : null}
        </>
    )
}

function StepTriggerConfigurationEvents({
    action,
    config,
}: {
    action: Extract<HogFlowAction, { type: 'trigger' }>
    config: Extract<HogFlowAction['config'], { type: 'event' }>
}): JSX.Element {
    const { setCampaignActionConfig } = useActions(campaignLogic)
    const { actionValidationErrorsById } = useValues(campaignLogic)
    const validationResult = actionValidationErrorsById[action.id]

    return (
        <>
            <div className="flex flex-col">
                <p className="mb-0">Choose which events or actions will enter a user into the campaign.</p>
            </div>

            <LemonField.Pure error={validationResult?.errors?.filters}>
                <HogFlowEventFilters
                    filters={config.filters ?? {}}
                    setFilters={(filters) =>
                        setCampaignActionConfig(action.id, { type: 'event', filters: filters ?? {} })
                    }
                    typeKey="campaign-trigger"
                    buttonCopy="Add trigger event"
                />
            </LemonField.Pure>

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
    const { setCampaignActionConfig } = useActions(campaignLogic)
    const { campaign, actionValidationErrorsById } = useValues(campaignLogic)
    const validationResult = actionValidationErrorsById[action.id]

    const webhookUrl = campaign.id === 'new' ? null : publicWebhooksHostOrigin() + '/public/webhooks/' + campaign.id

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
                    setCampaignActionConfig(action.id, {
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

function StepTriggerConfigurationTrackingPixel({
    action,
    config,
}: {
    action: Extract<HogFlowAction, { type: 'trigger' }>
    config: Extract<HogFlowAction['config'], { type: 'tracking_pixel' }>
}): JSX.Element {
    const { setCampaignActionConfig } = useActions(campaignLogic)
    const { campaign, actionValidationErrorsById } = useValues(campaignLogic)
    const validationResult = actionValidationErrorsById[action.id]

    const trackingPixelUrl =
        campaign.id !== 'new' ? `${publicWebhooksHostOrigin()}/public/webhooks/${campaign.id}` : null

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
                    setCampaignActionConfig(action.id, {
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

function ConversionGoalSection(): JSX.Element {
    const { setCampaignValue } = useActions(campaignLogic)
    const { campaign } = useValues(campaignLogic)

    return (
        <div className="flex flex-col py-2 w-full">
            <span className="text-md font-semibold">Conversion goal (optional)</span>
            <p>Define what a user must do to be considered converted.</p>

            <div className="flex gap-1 max-w-240">
                <div className="flex flex-col flex-2 gap-4">
                    <LemonField.Pure label="Detect conversion from property changes">
                        <PropertyFilters
                            buttonText="Add property conversion"
                            propertyFilters={campaign.conversion?.filters ?? []}
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.PersonProperties,
                                TaxonomicFilterGroupType.Cohorts,
                                TaxonomicFilterGroupType.HogQLExpression,
                            ]}
                            onChange={(filters) => setCampaignValue('conversion', { ...campaign.conversion, filters })}
                            pageKey="campaign-conversion-properties"
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
                                posthog.capture('messaging campaign event conversion clicked')
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
                        info="How long after entering the campaign should we check for conversion? After this window, users will be considered for conversion."
                    >
                        <LemonSelect
                            value={campaign.conversion?.window_minutes}
                            onChange={(value) =>
                                setCampaignValue('conversion', {
                                    ...campaign.conversion,
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
    const { setCampaignValue } = useActions(campaignLogic)
    const { campaign } = useValues(campaignLogic)

    return (
        <div className="flex flex-col flex-1 w-full py-2">
            <span className="text-md font-semibold">Exit condition</span>
            <p>Choose how your users move through the campaign.</p>

            <LemonField.Pure>
                <LemonRadio
                    value={campaign.exit_condition ?? 'exit_only_at_end'}
                    onChange={(value) => setCampaignValue('exit_condition', value)}
                    options={[
                        {
                            value: 'exit_only_at_end',
                            label: 'Exit at end of workflow',
                        },
                        {
                            value: 'exit_on_trigger_not_matched',
                            label: 'Exit on trigger not matched',
                        },
                        {
                            value: 'exit_on_conversion',
                            label: 'Exit on conversion',
                        },
                        {
                            value: 'exit_on_trigger_not_matched_or_conversion',
                            label: 'Exit on trigger not matched or conversion',
                        },
                    ]}
                />
            </LemonField.Pure>
        </div>
    )
}
