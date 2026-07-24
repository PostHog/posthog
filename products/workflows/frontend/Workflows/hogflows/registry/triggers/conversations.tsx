import { useActions } from 'kea'

import { IconBolt } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { HogFlowPropertyFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowFilters'
import {
    type EventTriggerConfig,
    registerTriggerType,
} from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

const SUPPORT_STATUS_VALUES = ['new', 'open', 'pending', 'on_hold', 'resolved'] as const
type SupportStatusValue = (typeof SUPPORT_STATUS_VALUES)[number]

function getEventId(config: EventTriggerConfig): string | null {
    const [firstEvent] = config.filters?.events ?? []
    return typeof firstEvent?.id === 'string' ? firstEvent.id : null
}

function isSupportStatusValue(value: unknown): value is SupportStatusValue {
    return typeof value === 'string' && SUPPORT_STATUS_VALUES.includes(value as SupportStatusValue)
}

function getSupportNewStatus(config: EventTriggerConfig): SupportStatusValue {
    const statusProperty = (config.filters?.properties ?? []).find((property: any) => property?.key === 'new_status')
    const statusValue = Array.isArray(statusProperty?.value) ? statusProperty.value[0] : statusProperty?.value
    return isSupportStatusValue(statusValue) ? statusValue : 'new'
}

function supportStatusChangedFilters(newStatus: SupportStatusValue): EventTriggerConfig['filters'] {
    return {
        events: [{ id: '$conversation_ticket_status_changed', type: 'events', name: 'Ticket status changed' }],
        properties: [
            {
                key: 'new_status',
                value: newStatus,
                operator: 'exact',
                type: 'event',
            },
        ],
    }
}

function StepTriggerConfigurationSupportStatusChanged({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const config = node.data.config as EventTriggerConfig
    const selectedStatus = getSupportNewStatus(config)

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This trigger runs when a ticket changes to the selected status.
            </p>
            <LemonField.Pure label="New status">
                <LemonSelect<SupportStatusValue>
                    value={selectedStatus}
                    options={[
                        { label: 'New', value: 'new' },
                        { label: 'Open', value: 'open' },
                        { label: 'Pending', value: 'pending' },
                        { label: 'On hold', value: 'on_hold' },
                        { label: 'Resolved', value: 'resolved' },
                    ]}
                    onChange={(value) =>
                        setWorkflowActionConfig(node.data.id, {
                            type: 'event',
                            filters: supportStatusChangedFilters(value),
                        })
                    }
                />
            </LemonField.Pure>
        </div>
    )
}

const SUPPORT_TRIGGER_META: Record<string, { name: string; description: string }> = {
    $conversation_message_received: {
        name: 'Ticket message received',
        description: 'This trigger runs when a customer sends a message on a ticket.',
    },
    $conversation_message_sent: {
        name: 'Ticket message sent',
        description: 'This trigger runs when a teammate sends a reply on a ticket.',
    },
    $conversation_ticket_assigned: {
        name: 'Ticket assigned',
        description: 'This trigger runs when a ticket is assigned to a teammate or team.',
    },
}

// A support trigger is fundamentally an event subscription; these extra property filters narrow it,
// e.g. only tickets assigned to one team (assignee_role_name), or a given priority/channel.
function StepTriggerConfigurationSupportFilters({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const config = node.data.config as EventTriggerConfig
    const eventId = getEventId(config) ?? '$conversation_message_received'
    const meta = SUPPORT_TRIGGER_META[eventId] ?? SUPPORT_TRIGGER_META['$conversation_message_received']

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">{meta.description}</p>
            <LemonField.Pure
                label="Filters"
                info="Only run when the ticket matches these properties. Filter on assignee_role_name to target a single team, or on priority, status, or channel_source."
            >
                <HogFlowPropertyFilters
                    filtersKey={`support-trigger-${node.data.id}`}
                    filters={config.filters ?? {}}
                    setFilters={(filters) =>
                        setWorkflowActionConfig(node.data.id, {
                            type: 'event',
                            filters: {
                                ...filters,
                                events: [{ id: eventId, type: 'events', name: meta.name }],
                            },
                        })
                    }
                    typeKey={`support-trigger-${node.data.id}`}
                />
            </LemonField.Pure>
        </div>
    )
}

registerTriggerType({
    value: 'support_ticket_created',
    label: 'New ticket created',
    icon: <IconBolt />,
    description: 'Trigger when a new support ticket is created',
    group: 'Support',
    matchConfig: (config) => config.type === 'event' && getEventId(config) === '$conversation_ticket_created',
    buildConfig: () => ({
        type: 'event',
        filters: {
            events: [{ id: '$conversation_ticket_created', type: 'events', name: 'New ticket created' }],
        },
    }),
})

registerTriggerType({
    value: 'support_ticket_status_changed',
    label: 'Ticket status changed',
    icon: <IconBolt />,
    description: 'Trigger when a ticket status changes to a selected status',
    group: 'Support',
    matchConfig: (config) => config.type === 'event' && getEventId(config) === '$conversation_ticket_status_changed',
    buildConfig: () => ({
        type: 'event',
        filters: supportStatusChangedFilters('new'),
    }),
    ConfigComponent: StepTriggerConfigurationSupportStatusChanged,
})

registerTriggerType({
    value: 'support_ticket_assigned',
    label: 'Ticket assigned',
    icon: <IconBolt />,
    description: 'Trigger when a ticket is assigned to a teammate or team',
    group: 'Support',
    matchConfig: (config) => config.type === 'event' && getEventId(config) === '$conversation_ticket_assigned',
    buildConfig: () => ({
        type: 'event',
        filters: {
            events: [{ id: '$conversation_ticket_assigned', type: 'events', name: 'Ticket assigned' }],
        },
    }),
    ConfigComponent: StepTriggerConfigurationSupportFilters,
})

registerTriggerType({
    value: 'support_message_sent',
    label: 'Ticket message sent',
    icon: <IconBolt />,
    description: 'Trigger when a teammate replies on a ticket',
    group: 'Support',
    matchConfig: (config) => config.type === 'event' && getEventId(config) === '$conversation_message_sent',
    buildConfig: () => ({
        type: 'event',
        filters: {
            events: [{ id: '$conversation_message_sent', type: 'events', name: 'Ticket message sent' }],
            // Match the trigger's stated intent — only teammate replies, never a customer message
            // that reached this event name. Keeps a "team reply" workflow from echoing the customer.
            properties: [{ key: 'author_type', value: ['team'], operator: 'exact', type: 'event' }],
        },
    }),
    ConfigComponent: StepTriggerConfigurationSupportFilters,
})

registerTriggerType({
    value: 'support_message_received',
    label: 'Ticket message received',
    icon: <IconBolt />,
    description: 'Trigger when a customer sends a message on a ticket',
    group: 'Support',
    matchConfig: (config) => config.type === 'event' && getEventId(config) === '$conversation_message_received',
    buildConfig: () => ({
        type: 'event',
        filters: {
            events: [{ id: '$conversation_message_received', type: 'events', name: 'Ticket message received' }],
        },
    }),
    ConfigComponent: StepTriggerConfigurationSupportFilters,
})
