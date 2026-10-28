import { Node } from '@xyflow/react'
import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconBolt, IconButton, IconClock, IconFilter, IconPeople, IconTarget, IconWebhooks } from '@posthog/icons'

import { getNotificationDescription } from 'scenes/hog-functions/list/notificationDescription'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { HogFunctionTemplateType } from '~/types'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { getDelayDescription } from './delayConfig'
import { StepConditionalBranchConfiguration } from './StepConditionalBranch'
import { StepDelayConfiguration } from './StepDelay'
import { StepExitConfiguration } from './StepExit'
import { StepFunctionConfiguration } from './StepFunction'
import { stepLook } from './stepLook'
import { StepRandomCohortBranchConfiguration } from './StepRandomCohortBranch'
import { StepTriggerConfiguration } from './StepTrigger'
import { StepWaitUntilConditionConfiguration } from './StepWaitUntilCondition'
import { StepWaitUntilTimeWindowConfiguration } from './StepWaitUntilTimeWindow'
import { getWaitUntilTimeWindowDescription } from './stepWaitUntilTimeWindowLogic'

type HogFlowStepPreview = {
    label: string
    icon?: JSX.Element
}

type HogFlowStepBuilder<T extends HogFlowAction['type']> = {
    type: T
    getPreviews: (
        action: Extract<HogFlowAction, { type: T }>,
        hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
    ) => HogFlowStepPreview[]
    renderConfiguration: (node: Node<Extract<HogFlowAction, { type: T }>>) => JSX.Element
}

type HogFlowStep<T extends HogFlowAction['type']> = {
    type: T
    icon: JSX.Element
    color: string
    previews: HogFlowStepPreview[]
    renderConfiguration: (node: Node<Extract<HogFlowAction, { type: T }>>) => JSX.Element
}

const TRIGGER_PREVIEWS: Record<string, HogFlowStepPreview> = {
    event: { label: 'Event', icon: <IconBolt /> },
    webhook: { label: 'Webhook', icon: <IconWebhooks /> },
    manual: { label: 'Manual', icon: <IconButton /> },
    tracking_pixel: { label: 'Tracking pixel', icon: <IconTarget /> },
    schedule: { label: 'Schedule', icon: <IconClock /> },
    batch: { label: 'Audience', icon: <IconPeople /> },
    'internal-event': { label: 'Internal event', icon: <IconBolt /> },
    'data-warehouse-table': { label: 'Data warehouse table', icon: <IconBolt /> },
    'data-warehouse-view': { label: 'Data warehouse view', icon: <IconBolt /> },
}

function getTriggerPreviews(action: Extract<HogFlowAction, { type: 'trigger' }>): HogFlowStepPreview[] {
    const config = action.config
    const preview = TRIGGER_PREVIEWS[config.type] ?? { label: config.type, icon: <IconBolt /> }
    if (!('filters' in config)) {
        return [preview]
    }

    const selectedFilter =
        config.type === 'event' || config.type === 'internal-event'
            ? (config.filters.events?.[0] ?? ('actions' in config.filters ? config.filters.actions?.[0] : null))
            : null
    const selectedName = selectedFilter?.name ?? selectedFilter?.id
    const propertyCount = config.filters.properties?.length ?? 0

    return [
        {
            ...preview,
            label: [
                preview.label,
                selectedName,
                propertyCount ? `${propertyCount} ${propertyCount === 1 ? 'filter' : 'filters'}` : null,
            ]
                .filter(Boolean)
                .join(' · '),
        },
    ]
}

function getFunctionPreviews(
    action: Extract<HogFlowAction, { type: 'function' }>,
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
): HogFlowStepPreview[] {
    const destination = getNotificationDescription({ inputs: action.config.inputs })
    if (action.config.template_id === 'template-webhook') {
        const method = String(action.config.inputs?.method?.value || 'POST').toUpperCase()
        return [{ label: destination ? `${method} ${destination}` : method }]
    }

    const templateName = hogFunctionTemplatesById[action.config.template_id]?.name ?? 'Destination'
    return [{ label: destination ? `${templateName} · ${destination}` : templateName }]
}

const HogFlowStepConfigs: Partial<{
    [K in HogFlowAction['type']]: HogFlowStepBuilder<K>
}> = {
    conditional_branch: {
        type: 'conditional_branch',
        getPreviews: (action) => {
            const count = action.config.conditions?.length ?? 0
            return [{ label: `${count} ${count === 1 ? 'condition' : 'conditions'}` }]
        },
        renderConfiguration: (node) => <StepConditionalBranchConfiguration key={node.id} node={node} />,
    },
    delay: {
        type: 'delay',
        getPreviews: (action) => [{ label: getDelayDescription(action.config).replace(/\.$/, '') }],
        renderConfiguration: (node) => <StepDelayConfiguration key={node.id} node={node} />,
    },
    exit: {
        type: 'exit',
        getPreviews: (action) => [{ label: action.config.reason || 'End workflow' }],
        renderConfiguration: (node) => <StepExitConfiguration key={node.id} node={node} />,
    },

    random_cohort_branch: {
        type: 'random_cohort_branch',
        getPreviews: (action) => {
            const count = action.config.cohorts?.length ?? 0
            return [{ label: `${count} ${count === 1 ? 'cohort' : 'cohorts'}` }]
        },
        renderConfiguration: (node) => <StepRandomCohortBranchConfiguration key={node.id} node={node} />,
    },
    trigger: {
        type: 'trigger',
        getPreviews: getTriggerPreviews,
        renderConfiguration: (node) => <StepTriggerConfiguration key={node.id} node={node} />,
    },
    wait_until_condition: {
        type: 'wait_until_condition',
        getPreviews: (action) => [{ label: `Up to ${action.config.max_wait_duration}` }],
        renderConfiguration: (node) => <StepWaitUntilConditionConfiguration key={node.id} node={node} />,
    },
    wait_until_time_window: {
        type: 'wait_until_time_window',
        getPreviews: (action) => [
            {
                label: getWaitUntilTimeWindowDescription(
                    action.config.day,
                    action.config.time,
                    action.config.timezone,
                    action.config.use_person_timezone,
                    action.config.fallback_timezone
                ).replace(/\.$/, ''),
            },
        ],
        renderConfiguration: (node) => <StepWaitUntilTimeWindowConfiguration key={node.id} node={node} />,
    },

    // We can remove these later
    function_email: {
        type: 'function_email',
        getPreviews: (action) => [
            {
                label: action.config.inputs?.email?.value?.to?.email
                    ? `To ${action.config.inputs.email.value.to.email}`
                    : 'Email',
            },
        ],
        renderConfiguration: (node) => <StepFunctionConfiguration key={node.id} node={node} />,
    },
    function_sms: {
        type: 'function_sms',
        getPreviews: (action) => [
            {
                label: action.config.inputs?.phoneNumber?.value
                    ? `To ${action.config.inputs.phoneNumber.value}`
                    : 'SMS',
            },
        ],
        renderConfiguration: (node) => <StepFunctionConfiguration key={node.id} node={node} />,
    },
    function_push: {
        type: 'function_push',
        getPreviews: (action) => [
            {
                label: action.config.inputs?.title?.value
                    ? String(action.config.inputs.title.value)
                    : 'Push notification',
            },
        ],
        renderConfiguration: (node) => <StepFunctionConfiguration key={node.id} node={node} />,
    },
    function: {
        type: 'function',
        getPreviews: getFunctionPreviews,
        renderConfiguration: (node) => <StepFunctionConfiguration key={node.id} node={node} />,
    },
} as const

// Type-safe accessor that preserves the key type
export function getHogFlowStep<T extends HogFlowAction['type']>(
    action: Extract<HogFlowAction, { type: T }>,
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>,
    isDarkModeOn = false
): HogFlowStep<T> | undefined {
    const type = action.type
    const builder = HogFlowStepConfigs[type] as HogFlowStepBuilder<T> | undefined
    const look = stepLook(action, hogFunctionTemplatesById, isDarkModeOn)
    if (!builder || !look) {
        return undefined
    }
    const conditionCount =
        (action.filters?.events?.length ?? 0) +
        (action.filters?.actions?.length ?? 0) +
        (action.filters?.properties?.length ?? 0)
    const previews = builder.getPreviews(action, hogFunctionTemplatesById)
    if (conditionCount) {
        previews.push({ label: String(conditionCount), icon: <IconFilter /> })
    }

    return {
        type,
        icon: look.icon,
        color: look.color,
        previews,
        renderConfiguration: builder.renderConfiguration,
    }
}

export function useHogFlowStep<T extends HogFlowAction['type']>(
    action?: Extract<HogFlowAction, { type: T }>
): HogFlowStep<T> | undefined {
    const { hogFunctionTemplatesById } = useValues(workflowLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    return useMemo(() => {
        if (!action) {
            return undefined
        }
        return getHogFlowStep(action, hogFunctionTemplatesById, isDarkModeOn)
    }, [action, hogFunctionTemplatesById, isDarkModeOn])
}
