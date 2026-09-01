import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { IconSlack } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { PropertyDefinition, PropertyDefinitionType, PropertyType } from '~/types'

import { HogFlowPropertyFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowFilters'
import { registerTriggerType } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

import { HogFlowAction } from '../../types'
import {
    SLACK_REACTOR_MODE_OPTIONS,
    SlackReactorMode,
    decodeSlackReactionFilters,
    encodeSlackReactionFilters,
    reactionName,
} from './slackReactionTriggerFilters'

export type SlackReactionTriggerConfig = {
    type: 'slack-reaction'
    filters: {
        properties?: any[]
    }
}

export function isSlackReactionTriggerConfig(
    config: Extract<HogFlowAction, { type: 'trigger' }>['config']
): config is SlackReactionTriggerConfig {
    return config.type === 'slack-reaction'
}

// Slack reactions never reach ClickHouse, so the advanced list has no stored values to
// autocomplete from and the properties have to be declared.
const ADVANCED_PROPERTIES: { key: string; type: PropertyType }[] = [
    { key: 'item_user', type: PropertyType.String },
    { key: 'item_ts', type: PropertyType.String },
    { key: 'is_ext_shared_channel', type: PropertyType.Boolean },
]

const ADVANCED_PROPERTY_DEFINITIONS: PropertyDefinition[] = ADVANCED_PROPERTIES.map(({ key, type }) => ({
    id: `slack-reaction-${key}`,
    name: key,
    type: PropertyDefinitionType.Event,
    property_type: type,
}))

function StepTriggerConfigurationSlackReaction({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)

    const config = node.data.config as SlackReactionTriggerConfig
    const filters = decodeSlackReactionFilters(config.filters?.properties)
    const validationResult = actionValidationErrorsById[node.data.id]
    const integrations = slackIntegrations ?? []

    const update = (changes: Partial<typeof filters>): void => {
        setWorkflowActionConfig(node.data.id, {
            type: 'slack-reaction',
            filters: { properties: encodeSlackReactionFilters({ ...filters, ...changes }) },
        })
    }

    if (integrationsLoading) {
        return <p className="mb-0 text-sm text-muted-alt">Loading Slack connections…</p>
    }

    if (integrations.length === 0) {
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
                This workflow runs once each time someone reacts with one of your emoji in the channel you pick. Runs
                have no associated person, so person-dependent steps are unavailable.
            </p>

            <LemonField.Pure
                label="Channel"
                error={validationResult?.errors?.channel}
                info="PostHog only receives reactions from channels the Slack bot has been invited to."
            >
                <SlackChannelPicker
                    integration={integrations[0]}
                    value={filters.channel ?? undefined}
                    onChange={(value) => update({ channel: value })}
                />
            </LemonField.Pure>

            <LemonField.Pure
                label="Emoji"
                error={validationResult?.errors?.reactions}
                info="Type the emoji name without colons, for example mag. Skin tone is ignored, so one entry covers everyone."
            >
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={filters.reactions}
                    options={filters.reactions.map((name) => ({ key: name, label: `:${name}:` }))}
                    placeholder="mag"
                    onChange={(reactions) => update({ reactions: reactions.map(reactionName).filter(Boolean) })}
                    data-attr="slack-reaction-trigger-emoji"
                />
            </LemonField.Pure>

            <LemonField.Pure
                label="Who can start a run"
                info="Reactions PostHog adds never start a run, so a workflow can react back without triggering itself."
            >
                <LemonSelect<SlackReactorMode>
                    value={filters.reactorMode}
                    options={SLACK_REACTOR_MODE_OPTIONS.map(({ value, label, description }) => ({
                        value,
                        label,
                        labelInMenu: (
                            <div className="flex flex-col py-1">
                                <span>{label}</span>
                                <span className="text-xs text-muted-alt">{description}</span>
                            </div>
                        ),
                    }))}
                    onChange={(reactorMode) => update({ reactorMode, reactorIds: [] })}
                    data-attr="slack-reaction-trigger-reactor-mode"
                />
            </LemonField.Pure>

            {filters.reactorMode === 'specific_people' && (
                <LemonField.Pure
                    label="Slack user IDs"
                    error={validationResult?.errors?.reactorIds}
                    info="Find an ID from the member profile in Slack, under 'Copy member ID'."
                >
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={filters.reactorIds}
                        options={filters.reactorIds.map((id) => ({ key: id, label: id }))}
                        placeholder="Slack user IDs, e.g. U01ABCDEF"
                        onChange={(reactorIds) => update({ reactorIds })}
                        data-attr="slack-reaction-trigger-reactor-ids"
                    />
                </LemonField.Pure>
            )}

            <LemonField.Pure
                label="Additional filters"
                info="Match on who wrote the message that was reacted to, or other fields."
            >
                <HogFlowPropertyFilters
                    filtersKey={`slack-reaction-trigger-${node.data.id}`}
                    filters={{ properties: filters.additional }}
                    setFilters={(next) => update({ additional: next?.properties ?? [] })}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    propertyAllowList={{
                        [TaxonomicFilterGroupType.EventProperties]: ADVANCED_PROPERTIES.map((p) => p.key),
                    }}
                    propertyDefinitionsOverride={ADVANCED_PROPERTY_DEFINITIONS}
                    taxonomicFilterOptionsFromProp={{
                        [TaxonomicFilterGroupType.EventProperties]: ADVANCED_PROPERTIES.map((p) => ({ name: p.key })),
                    }}
                    inline
                />
            </LemonField.Pure>
        </div>
    )
}

registerTriggerType({
    value: 'slack-reaction',
    label: 'Slack reaction added',
    icon: <IconSlack />,
    description: 'Trigger when someone reacts to a message in a Slack channel',
    group: 'Slack',
    featureFlag: 'slack-workflow-triggers',
    matchConfig: (config) => isSlackReactionTriggerConfig(config),
    buildConfig: () => ({
        type: 'slack-reaction',
        filters: {
            properties: encodeSlackReactionFilters({
                channel: null,
                reactions: [],
                reactorMode: 'anyone',
                reactorIds: [],
                additional: [],
            }),
        },
    }),
    validate: (config): { valid: boolean; errors: Record<string, string> } | null => {
        if (config.type !== 'slack-reaction') {
            return null
        }
        const filters = decodeSlackReactionFilters(config.filters?.properties)
        if (!filters.channel) {
            return { valid: false, errors: { channel: 'Please pick a Slack channel' } }
        }
        // Without an emoji every reaction starts a run, including the :eyes: a run adds to the
        // message it is working on, which would make a replying workflow retrigger itself.
        if (!filters.reactions.length) {
            return { valid: false, errors: { reactions: 'Add at least one emoji, or every reaction starts a run' } }
        }
        if (filters.reactorMode === 'specific_people' && !filters.reactorIds.length) {
            return {
                valid: false,
                errors: { reactorIds: 'Add at least one Slack ID, or the trigger will never fire' },
            }
        }
        return { valid: true, errors: {} }
    },
    ConfigComponent: StepTriggerConfigurationSlackReaction,
})
