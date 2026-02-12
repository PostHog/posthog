import { useActions } from 'kea'

import { IconBolt } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { registerTriggerType } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

const SUPPORT_STATUS_VALUES = ['new', 'open', 'pending', 'on_hold', 'resolved'] as const
type SupportStatusValue = (typeof SUPPORT_STATUS_VALUES)[number]

type EventTriggerConfig = {
    type: 'event'
    filters: {
        events?: any[]
        properties?: any[]
        actions?: any[]
        filter_test_accounts?: boolean
    }
}

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

function StepTriggerConfigurationSupportMessage({ node }: { node: any }): JSX.Element {
    const config = node.data.config as EventTriggerConfig
    const eventId = getEventId(config)
    const kind = eventId === '$conversation_message_sent' ? 'sent' : 'received'

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                {kind === 'sent'
                    ? 'This trigger runs when a teammate sends a reply on a ticket.'
                    : 'This trigger runs when a customer sends a message on a ticket.'}
            </p>
        </div>
    )
}

registerTriggerType({
    value: 'support_ticket_status_changed',
    label: 'Ticket status changed',
    icon: <IconBolt />,
    description: 'Trigger when a ticket status changes to a selected status',
    featureFlag: FEATURE_FLAGS.PRODUCT_SUPPORT,
    matchConfig: (config) => config.type === 'event' && getEventId(config) === '$conversation_ticket_status_changed',
    buildConfig: () => ({
        type: 'event',
        filters: supportStatusChangedFilters('new'),
    }),
    ConfigComponent: StepTriggerConfigurationSupportStatusChanged,
})

registerTriggerType({
    value: 'support_message_sent',
    label: 'Ticket message sent',
    icon: <IconBolt />,
    description: 'Trigger when a teammate replies on a ticket',
    featureFlag: FEATURE_FLAGS.PRODUCT_SUPPORT,
    matchConfig: (config) => config.type === 'event' && getEventId(config) === '$conversation_message_sent',
    buildConfig: () => ({
        type: 'event',
        filters: {
            events: [{ id: '$conversation_message_sent', type: 'events', name: 'Ticket message sent' }],
        },
    }),
    ConfigComponent: StepTriggerConfigurationSupportMessage,
})

registerTriggerType({
    value: 'support_message_received',
    label: 'Ticket message received',
    icon: <IconBolt />,
    description: 'Trigger when a customer sends a message on a ticket',
    featureFlag: FEATURE_FLAGS.PRODUCT_SUPPORT,
    matchConfig: (config) => config.type === 'event' && getEventId(config) === '$conversation_message_received',
    buildConfig: () => ({
        type: 'event',
        filters: {
            events: [{ id: '$conversation_message_received', type: 'events', name: 'Ticket message received' }],
        },
    }),
    ConfigComponent: StepTriggerConfigurationSupportMessage,
})
