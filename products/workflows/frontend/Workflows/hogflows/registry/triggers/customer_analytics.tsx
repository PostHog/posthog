import { useActions, useValues } from 'kea'

import { IconBolt } from '@posthog/icons'
import { LemonInputSelect } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { tagsModel } from '~/models/tagsModel'

import {
    type EventTriggerConfig,
    registerTriggerType,
} from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

const ACCOUNT_TAG_ADDED_EVENT = '$account_tag_added'

function getEventId(config: EventTriggerConfig): string | null {
    const [firstEvent] = config.filters?.events ?? []
    return typeof firstEvent?.id === 'string' ? firstEvent.id : null
}

export function getSelectedTags(config: EventTriggerConfig): string[] {
    const tagProperty = (config.filters?.properties ?? []).find((property: any) => property?.key === 'tag')
    if (!tagProperty) {
        return []
    }
    const values = Array.isArray(tagProperty.value) ? tagProperty.value : [tagProperty.value]
    return values.filter((tag: unknown): tag is string => typeof tag === 'string')
}

export function accountTagAddedFilters(tags: string[]): EventTriggerConfig['filters'] {
    return {
        events: [{ id: ACCOUNT_TAG_ADDED_EVENT, type: 'events', name: 'Account tag added' }],
        properties: tags.length > 0 ? [{ key: 'tag', value: tags, operator: 'exact', type: 'event' }] : [],
    }
}

function StepTriggerConfigurationAccountTagAdded({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { tags, tagsLoading } = useValues(tagsModel)
    const config = node.data.config as EventTriggerConfig
    const selectedTags = getSelectedTags(config)

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This trigger runs when a tag is added to an account. Leave empty to run for any tag.
            </p>
            <LemonField.Pure label="Tags">
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={selectedTags}
                    loading={tagsLoading}
                    placeholder="Any tag"
                    options={tags.map((tag: string) => ({ key: tag, label: tag }))}
                    onChange={(value) =>
                        setWorkflowActionConfig(node.data.id, {
                            type: 'event',
                            filters: accountTagAddedFilters(value),
                        })
                    }
                    data-attr="account-tag-added-trigger-tags"
                />
            </LemonField.Pure>
        </div>
    )
}

registerTriggerType({
    value: 'account_tag_added',
    label: 'Account tag added',
    icon: <IconBolt />,
    description: 'Trigger when a tag is added to an account',
    group: 'Customer analytics',
    featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
    matchConfig: (config) => config.type === 'event' && getEventId(config) === ACCOUNT_TAG_ADDED_EVENT,
    buildConfig: () => ({
        type: 'event',
        filters: accountTagAddedFilters([]),
    }),
    ConfigComponent: StepTriggerConfigurationAccountTagAdded,
})
