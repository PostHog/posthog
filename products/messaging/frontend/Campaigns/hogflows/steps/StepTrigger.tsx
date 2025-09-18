import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconBolt, IconPlusSmall, IconWebhooks } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonLabel, LemonSelect, LemonTag, lemonToast } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
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
