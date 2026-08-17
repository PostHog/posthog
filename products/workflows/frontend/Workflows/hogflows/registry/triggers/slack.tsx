import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { IconSlack } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { PropertyDefinition, PropertyDefinitionType, PropertyFilterType, PropertyOperator, PropertyType } from '~/types'

import { HogFlowPropertyFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowFilters'
import { registerTriggerType } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

import { HogFlowAction } from '../../types'

export type SlackMessageTriggerConfig = {
    type: 'slack-message'
    filters: {
        properties?: any[]
    }
}

export function isSlackMessageTriggerConfig(
    config: Extract<HogFlowAction, { type: 'trigger' }>['config']
): config is SlackMessageTriggerConfig {
    return config.type === 'slack-message'
}

const CHANNEL_PROPERTY = 'channel'

// The message properties worth filtering on. Slack messages never reach ClickHouse, so there is no
// stored data to autocomplete from and the list has to be declared.
const SLACK_MESSAGE_PROPERTIES: { key: string; label: string; type: PropertyType }[] = [
    { key: 'channel', label: 'Channel ID', type: PropertyType.String },
    { key: 'user', label: 'Slack user ID of the poster', type: PropertyType.String },
    { key: 'bot_id', label: 'Bot ID, set when an app posted', type: PropertyType.String },
    { key: 'app_id', label: 'App ID, set when an app posted', type: PropertyType.String },
    { key: 'text', label: 'Message text', type: PropertyType.String },
    { key: 'subtype', label: 'Message subtype', type: PropertyType.String },
    { key: 'thread_ts', label: 'Thread timestamp', type: PropertyType.String },
    { key: 'is_thread_reply', label: 'Posted as a thread reply', type: PropertyType.Boolean },
    { key: 'is_ext_shared_channel', label: 'Channel is shared with another org', type: PropertyType.Boolean },
]

const SLACK_PROPERTY_DEFINITIONS: PropertyDefinition[] = SLACK_MESSAGE_PROPERTIES.map(({ key, type }) => ({
    id: `slack-message-${key}`,
    name: key,
    type: PropertyDefinitionType.Event,
    property_type: type,
}))

function getChannel(config: SlackMessageTriggerConfig): string | null {
    const entry = (config.filters?.properties ?? []).find((property: any) => property?.key === CHANNEL_PROPERTY)
    const value = Array.isArray(entry?.value) ? entry.value[0] : entry?.value
    return typeof value === 'string' && value ? value : null
}

/** Everything except the channel, which has its own picker above the filter list. */
function getOtherProperties(config: SlackMessageTriggerConfig): any[] {
    return (config.filters?.properties ?? []).filter((property: any) => property?.key !== CHANNEL_PROPERTY)
}

function channelProperty(channel: string): Record<string, any> {
    return {
        key: CHANNEL_PROPERTY,
        value: [channel],
        operator: PropertyOperator.Exact,
        type: PropertyFilterType.Event,
    }
}

function StepTriggerConfigurationSlackMessage({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)

    const config = node.data.config as SlackMessageTriggerConfig
    const channel = getChannel(config)
    const otherProperties = getOtherProperties(config)
    const validationResult = actionValidationErrorsById[node.data.id]
    const integrations = slackIntegrations ?? []

    const updateProperties = (properties: any[]): void => {
        setWorkflowActionConfig(node.data.id, { type: 'slack-message', filters: { properties } })
    }

    if (!integrationsLoading && integrations.length === 0) {
        return (
            <LemonBanner type="warning" className="w-full">
                <p className="mb-0">
                    This trigger needs a Slack connection, and this project doesn't have one yet. Connect Slack, invite
                    the bot to a channel, then come back and pick it.{' '}
                    <Link to={urls.settings('project-integrations')} className="font-semibold">
                        Connect Slack
                    </Link>
                </p>
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This workflow runs once for each message posted in the channel you pick. Runs have no associated person,
                so person-dependent steps are unavailable.
            </p>

            <LemonField.Pure
                label="Channel"
                error={validationResult?.errors?.channel}
                info="PostHog only receives messages from channels the Slack bot has been invited to."
            >
                {integrations.length > 0 && (
                    <SlackChannelPicker
                        integration={integrations[0]}
                        value={channel ?? undefined}
                        onChange={(value) =>
                            updateProperties(value ? [channelProperty(value), ...otherProperties] : otherProperties)
                        }
                    />
                )}
            </LemonField.Pure>

            <LemonField.Pure
                label="Only run for some messages"
                info="Leave empty to run on every message in the channel. The default excludes app and bot posts."
            >
                <HogFlowPropertyFilters
                    filtersKey={`slack-message-trigger-${node.data.id}`}
                    filters={{ properties: otherProperties }}
                    setFilters={(filters) =>
                        updateProperties([
                            ...(channel ? [channelProperty(channel)] : []),
                            ...(filters?.properties ?? []),
                        ])
                    }
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    propertyAllowList={{
                        [TaxonomicFilterGroupType.EventProperties]: SLACK_MESSAGE_PROPERTIES.map((p) => p.key),
                    }}
                    propertyDefinitionsOverride={SLACK_PROPERTY_DEFINITIONS}
                />
            </LemonField.Pure>
        </div>
    )
}

registerTriggerType({
    value: 'slack-message',
    label: 'Slack message posted',
    icon: <IconSlack />,
    description: 'Trigger when someone posts in a Slack channel',
    group: 'Slack',
    featureFlag: 'slack-workflow-triggers',
    matchConfig: (config) => isSlackMessageTriggerConfig(config),
    buildConfig: () => ({
        type: 'slack-message',
        filters: {
            // A workflow that posts back to Slack would otherwise retrigger on its own message, so
            // apps and bots are excluded until someone deliberately removes this.
            properties: [
                {
                    key: 'bot_id',
                    value: 'is_not_set',
                    operator: PropertyOperator.IsNotSet,
                    type: PropertyFilterType.Event,
                },
            ],
        },
    }),
    validate: (config): { valid: boolean; errors: Record<string, string> } | null => {
        if (config.type !== 'slack-message') {
            return null
        }
        if (!getChannel(config)) {
            return { valid: false, errors: { channel: 'Please pick a Slack channel' } }
        }
        return { valid: true, errors: {} }
    },
    ConfigComponent: StepTriggerConfigurationSlackMessage,
})
