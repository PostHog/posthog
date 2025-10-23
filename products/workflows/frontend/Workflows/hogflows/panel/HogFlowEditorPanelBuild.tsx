import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconDrag } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonInput, SpinnerOverlay } from '@posthog/lemon-ui'

import { hogFunctionTemplateListLogic } from 'scenes/hog-functions/list/hogFunctionTemplateListLogic'
import { HogFunctionStatusTag } from 'scenes/hog-functions/misc/HogFunctionStatusTag'

import { HogFunctionTemplateType } from '~/types'

import { CreateActionType, hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import { HogFlowAction } from '../types'

export const ACTION_NODES_TO_SHOW: CreateActionType[] = [
    {
        type: 'function_email',
        name: 'Email',
        description: 'Send an email to the user.',
        config: {
            template_id: 'template-email',
            inputs: {},
        },
    },
    {
        type: 'function_sms',
        name: 'SMS',
        description: 'Send an SMS to the user.',
        config: {
            template_id: 'template-twilio',
            inputs: {},
        },
    },
    {
        type: 'function',
        name: 'Slack',
        description: 'Send a Slack message to the user.',
        config: { template_id: 'template-slack', inputs: {} },
    },
    {
        type: 'function',
        name: 'Webhook',
        description: 'Send a Webhook to the user.',
        config: { template_id: 'template-webhook', inputs: {} },
    },
]

export const DELAY_NODES_TO_SHOW: CreateActionType[] = [
    { type: 'delay', name: 'Delay', description: 'Wait for a specified duration.', config: { delay_duration: '10m' } },
    {
        type: 'wait_until_time_window',
        name: 'Wait until window',
        description: 'Wait until a specified time window.',
        config: {
            timezone: null,
            day: 'any',
            time: 'any',
        },
    },
    {
        type: 'wait_until_condition',
        name: 'Wait until condition',
        description: 'Wait until a condition is met or a duration has passed.',
        branchEdges: 1,
        config: {
            condition: { filters: null },
            max_wait_duration: '5m',
        },
    },
]

export const LOGIC_NODES_TO_SHOW: CreateActionType[] = [
    {
        type: 'conditional_branch',
        name: 'Conditional branch',
        description: 'Branch using conditions on event or person properties.',
        branchEdges: 1,
        config: {
            conditions: [
                {
                    filters: {
                        events: [
                            {
                                id: '$pageview',
                                name: '$pageview',
                                type: 'events',
                            },
                        ],
                    },
                },
            ],
        },
    },
    {
        type: 'random_cohort_branch',
        name: 'Cohort branch',
        description: 'Randomly branch off based on cohort percentages.',
        branchEdges: 1,
        config: {
            cohorts: [
                {
                    percentage: 50,
                },
            ],
        },
    },
]

export const POSTHOG_NODES_TO_SHOW: CreateActionType[] = [
    {
        type: 'function',
        name: 'Capture event',
        description: 'Capture an event to PostHog.',
        config: { template_id: 'template-posthog-capture', inputs: {} },
    },
    {
        type: 'function',
        name: 'Update person property',
        description: 'Set properties of a person in PostHog.',
        config: { template_id: 'template-posthog-update-person-properties', inputs: {} },
    },
    {
        type: 'function',
        name: 'Set group property',
        description: 'Set properties of a group in PostHog.',
        config: { template_id: 'template-posthog-group-identify', inputs: {} },
    },
]

const TEMPLATE_IDS_AT_TOP_LEVEL: string[] = [
    ...ACTION_NODES_TO_SHOW.map((action) => (action.config as any).template_id),
    ...DELAY_NODES_TO_SHOW.map((action) => (action.config as any).template_id),
    ...LOGIC_NODES_TO_SHOW.map((action) => (action.config as any).template_id),
    ...POSTHOG_NODES_TO_SHOW.map((action) => (action.config as any).template_id),
].filter((t) => !!t)

function HogFlowEditorToolbarNode({
    action,
    onDragStart: onDragStartProp,
    children,
}: {
    action: CreateActionType
    onDragStart?: (event: React.DragEvent) => void
    children?: React.ReactNode
}): JSX.Element | null {
    const { setNewDraggingNode } = useActions(hogFlowEditorLogic)

    const onDragStart = (event: React.DragEvent): void => {
        setNewDraggingNode(action)
        event.dataTransfer.setData('application/reactflow', action.type)
        event.dataTransfer.effectAllowed = 'move'
        onDragStartProp?.(event)
    }

    const step = useHogFlowStep(action as HogFlowAction)

    if (!step) {
        return null
    }

    return (
        <div draggable onDragStart={onDragStart}>
            <LemonButton
                icon={<span style={{ color: step.color }}>{step.icon}</span>}
                sideIcon={<IconDrag />}
                fullWidth
            >
                {children ?? action.name}
            </LemonButton>
        </div>
    )
}

// For now we only want to show destinations that do not have secrets and not coming soon
const customFilterFunction = (template: HogFunctionTemplateType): boolean => {
    if (template.type !== 'destination' || TEMPLATE_IDS_AT_TOP_LEVEL.includes(template.id)) {
        return false
    }

    if (template.type === 'destination' && template.inputs_schema?.some((input) => input.secret)) {
        return false
    }

    if (template.status === 'coming_soon') {
        return false
    }

    return true
}

function HogFunctionTemplatesChooser(): JSX.Element {
    const logic = hogFunctionTemplateListLogic({
        type: 'destination',
        customFilterFunction,
    })

    const { loading, filteredTemplates, filters } = useValues(logic)
    const { loadHogFunctionTemplates, setFilters } = useActions(logic)

    const [popoverOpen, setPopoverOpen] = useState(false)

    useEffect(() => {
        loadHogFunctionTemplates()
    }, [loadHogFunctionTemplates])

    return (
        <div>
            <LemonDropdown
                closeOnClickInside={false}
                visible={popoverOpen}
                onClickOutside={() => setPopoverOpen(false)}
                placement="bottom-end"
                overlay={
                    <div className="flex flex-col w-100 h-120 flex-1 overflow-hidden gap-1">
                        <LemonInput
                            placeholder="Search..."
                            value={filters.search ?? ''}
                            onChange={(e) => setFilters({ ...filters, search: e })}
                            autoFocus
                        />

                        {loading ? (
                            <SpinnerOverlay />
                        ) : (
                            <ul className="overflow-y-auto flex-1">
                                {filteredTemplates.map((template) => (
                                    <li key={template.type}>
                                        <HogFlowEditorToolbarNode
                                            action={{
                                                type: 'function',
                                                name: template.name,
                                                description:
                                                    typeof template.description === 'string'
                                                        ? template.description
                                                        : '',
                                                config: { template_id: template.id, inputs: {} },
                                            }}
                                        >
                                            <div className="py-1 flex items-center gap-1 flex-1">
                                                <div className="flex-1">
                                                    <div>{template.name}</div>
                                                    <div className="text-xs text-muted">{template.description}</div>
                                                </div>
                                                {template.status && <HogFunctionStatusTag status={template.status} />}
                                            </div>
                                        </HogFlowEditorToolbarNode>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                }
            >
                <LemonButton fullWidth onClick={() => setPopoverOpen(!popoverOpen)}>
                    More
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}

export function HogFlowEditorPanelBuild(): JSX.Element {
    return (
        <div className="flex overflow-y-auto flex-col gap-px p-2">
            <span className="flex gap-2 text-sm font-semibold mt-2 items-center">
                Dispatch <LemonDivider className="flex-1" />
            </span>
            {ACTION_NODES_TO_SHOW.map((node, index) => (
                <HogFlowEditorToolbarNode key={`${node.type}-${index}`} action={node} />
            ))}
            <HogFunctionTemplatesChooser />

            <span className="flex gap-2 text-sm font-semibold mt-2 items-center">
                Delays <LemonDivider className="flex-1" />
            </span>
            {DELAY_NODES_TO_SHOW.map((action, index) => (
                <HogFlowEditorToolbarNode key={`${action.type}-${index}`} action={action} />
            ))}

            <span className="flex gap-2 text-sm font-semibold mt-2 items-center">
                Audience split <LemonDivider className="flex-1" />
            </span>
            {LOGIC_NODES_TO_SHOW.map((action, index) => (
                <HogFlowEditorToolbarNode key={`${action.type}-${index}`} action={action} />
            ))}

            <span className="flex gap-2 text-sm font-semibold mt-2 items-center">
                PostHog actions <LemonDivider className="flex-1" />
            </span>
            {POSTHOG_NODES_TO_SHOW.map((action, index) => (
                <HogFlowEditorToolbarNode key={`${action.type}-${index}`} action={action} />
            ))}
        </div>
    )
}
