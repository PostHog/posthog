import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInputSelect, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

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
    SLACK_POSTER_MODE_OPTIONS,
    SlackPosterMode,
    decodeSlackFilters,
    encodeSlackFilters,
} from './slackTriggerFilters'

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

// Slack messages never reach ClickHouse, so the advanced list has no stored values to
// autocomplete from and the properties have to be declared.
const ADVANCED_PROPERTIES: { key: string; type: PropertyType }[] = [
    { key: 'text', type: PropertyType.String },
    { key: 'subtype', type: PropertyType.String },
    { key: 'channel_type', type: PropertyType.String },
    { key: 'is_thread_reply', type: PropertyType.Boolean },
    { key: 'is_ext_shared_channel', type: PropertyType.Boolean },
]

const ADVANCED_PROPERTY_DEFINITIONS: PropertyDefinition[] = ADVANCED_PROPERTIES.map(({ key, type }) => ({
    id: `slack-message-${key}`,
    name: key,
    type: PropertyDefinitionType.Event,
    property_type: type,
}))

const POSTER_ID_PLACEHOLDER: Record<SlackPosterMode, string> = {
    anyone: '',
    people: '',
    apps: '',
    specific_people: 'Slack user IDs, e.g. U01ABCDEF',
    specific_apps: 'Slack app IDs, e.g. A01ABCDEF',
}

function StepTriggerConfigurationSlackMessage({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)

    const config = node.data.config as SlackMessageTriggerConfig
    const filters = decodeSlackFilters(config.filters?.properties)
    const validationResult = actionValidationErrorsById[node.data.id]
    const integrations = slackIntegrations ?? []
    const wantsIds = filters.posterMode === 'specific_people' || filters.posterMode === 'specific_apps'

    const update = (changes: Partial<typeof filters>): void => {
        setWorkflowActionConfig(node.data.id, {
            type: 'slack-message',
            filters: { properties: encodeSlackFilters({ ...filters, ...changes }) },
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
                This workflow runs once for each message posted in the channel you pick. Runs have no associated person,
                so person-dependent steps are unavailable.
            </p>

            <LemonField.Pure
                label="Channel"
                error={validationResult?.errors?.channel}
                info="PostHog only receives messages from channels the Slack bot has been invited to."
            >
                <SlackChannelPicker
                    integration={integrations[0]}
                    value={filters.channel ?? undefined}
                    onChange={(value) => update({ channel: value })}
                />
            </LemonField.Pure>

            <LemonField.Pure
                label="Who can start a run"
                info="Messages posted by PostHog never start a run, so a workflow can reply in Slack without triggering itself."
            >
                <LemonSelect<SlackPosterMode>
                    value={filters.posterMode}
                    options={SLACK_POSTER_MODE_OPTIONS.map(({ value, label, description }) => ({
                        value,
                        label,
                        labelInMenu: (
                            <div className="flex flex-col py-1">
                                <span>{label}</span>
                                <span className="text-xs text-muted-alt">{description}</span>
                            </div>
                        ),
                    }))}
                    onChange={(posterMode) => update({ posterMode, posterIds: [] })}
                    data-attr="slack-trigger-poster-mode"
                />
            </LemonField.Pure>

            {wantsIds && (
                <LemonField.Pure
                    label={filters.posterMode === 'specific_people' ? 'Slack user IDs' : 'Slack app IDs'}
                    error={validationResult?.errors?.posterIds}
                    info="Find an ID from the member or app profile in Slack, under 'Copy member ID' or the app's About tab."
                >
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={filters.posterIds}
                        options={filters.posterIds.map((id) => ({ key: id, label: id }))}
                        placeholder={POSTER_ID_PLACEHOLDER[filters.posterMode]}
                        onChange={(posterIds) => update({ posterIds })}
                        data-attr="slack-trigger-poster-ids"
                    />
                </LemonField.Pure>
            )}

            <LemonSwitch
                checked={filters.topLevelOnly}
                onChange={(topLevelOnly) => update({ topLevelOnly })}
                label="Ignore replies inside threads"
                bordered
                data-attr="slack-trigger-top-level-only"
            />

            <LemonField.Pure label="Additional filters" info="Match on the message text, subtype, or other fields.">
                <HogFlowPropertyFilters
                    filtersKey={`slack-message-trigger-${node.data.id}`}
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
            properties: encodeSlackFilters({
                channel: null,
                posterMode: 'people',
                posterIds: [],
                topLevelOnly: true,
                additional: [],
            }),
        },
    }),
    validate: (config): { valid: boolean; errors: Record<string, string> } | null => {
        if (config.type !== 'slack-message') {
            return null
        }
        const filters = decodeSlackFilters(config.filters?.properties)
        if (!filters.channel) {
            return { valid: false, errors: { channel: 'Please pick a Slack channel' } }
        }
        const wantsIds = filters.posterMode === 'specific_people' || filters.posterMode === 'specific_apps'
        if (wantsIds && !filters.posterIds.length) {
            return {
                valid: false,
                errors: { posterIds: 'Add at least one Slack ID, or the trigger will never fire' },
            }
        }
        return { valid: true, errors: {} }
    },
    ConfigComponent: StepTriggerConfigurationSlackMessage,
})
