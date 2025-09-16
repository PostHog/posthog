import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { IconBolt, IconWebhooks } from '@posthog/icons'
import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'

import { campaignLogic } from '../../campaignLogic'
import { HogFlowFilters } from '../filters/HogFlowFilters'
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

    const webhookTriggerEnabled = useFeatureFlag('MESSAGING_TRIGGER_WEBHOOK')

    if (!webhookTriggerEnabled && node.data.config.type === 'event') {
        return <StepTriggerConfigurationEvents action={node.data} config={node.data.config} />
    }

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
                    ]}
                    value={type}
                    placeholder="Select trigger type"
                    onChange={(value) => {
                        value === 'event'
                            ? setCampaignActionConfig(node.id, { type: 'event', filters: {} })
                            : setCampaignActionConfig(node.id, {
                                  type: 'webhook',
                                  template_id: 'template-source-webhook',
                                  inputs: {},
                              })
                    }}
                />
            </LemonField.Pure>
            {node.data.config.type === 'event' ? (
                <StepTriggerConfigurationEvents action={node.data} config={node.data.config} />
            ) : (
                <StepTriggerConfigurationWebhook action={node.data} config={node.data.config} />
            )}
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
                <HogFlowFilters
                    filters={config.filters ?? {}}
                    setFilters={(filters) =>
                        setCampaignActionConfig(action.id, { type: 'event', filters: filters ?? {} })
                    }
                    typeKey="campaign-trigger"
                    buttonCopy="Add trigger event"
                />
            </LemonField.Pure>
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

    return (
        <>
            <div className="p-2 rounded border deprecated-space-y-2 bg-surface-secondary">
                <LemonLabel>Webhook URL</LemonLabel>
                {campaign.id === 'new' ? (
                    <div className="text-xs text-muted italic border rounded p-1 bg-surface-primary">
                        The webhook URL will be shown here once you save the workflow
                    </div>
                ) : (
                    <CodeSnippet thing="Webhook URL">
                        {publicWebhooksHostOrigin() + '/public/webhooks/' + campaign.id}
                    </CodeSnippet>
                )}

                <p className="text-sm">
                    The webhook can be called with a POST request and any JSON payload. You can then use the
                    configuration options to parse the <code>request.body</code> or <code>request.headers</code> to map
                    to the required fields.
                </p>
            </div>
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
