import { Node } from '@xyflow/react'
import { useValues } from 'kea'
import { useMemo } from 'react'

import {
    IconBolt,
    IconButton,
    IconClock,
    IconDay,
    IconDecisionTree,
    IconFilter,
    IconHourglass,
    IconLeave,
    IconLetter,
    IconNotification,
    IconPeople,
    IconPercentage,
    IconTarget,
    IconWebhooks,
} from '@posthog/icons'

import { IconTwilio } from 'lib/lemon-ui/icons'
import { getNotificationDescription } from 'scenes/hog-functions/list/notificationDescription'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { HogFunctionTemplateType } from '~/types'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { StepConditionalBranchConfiguration } from './StepConditionalBranch'
import { StepDelayConfiguration } from './StepDelay'
import { getDelayDescription } from './stepDelayLogic'
import { StepExitConfiguration } from './StepExit'
import { StepFunctionConfiguration } from './StepFunction'
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
    icon: (
        action: Extract<HogFlowAction, { type: T }>,
        hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
    ) => JSX.Element
    color: (action: Extract<HogFlowAction, { type: T }>, isDarkModeOn: boolean) => string
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
        const method = String(action.config.inputs.method?.value || 'POST').toUpperCase()
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
        icon: () => <IconDecisionTree />,
        color: (_, isDarkModeOn) => (isDarkModeOn ? '#35C46F' : '#005841'),
        getPreviews: (action) => [
            {
                label: `${action.config.conditions.length} ${action.config.conditions.length === 1 ? 'condition' : 'conditions'}`,
            },
        ],
        renderConfiguration: (node) => <StepConditionalBranchConfiguration key={node.id} node={node} />,
    },
    delay: {
        type: 'delay',
        icon: () => <IconClock />,
        color: () => '#a20031',
        getPreviews: (action) => [{ label: getDelayDescription(action.config).replace(/\.$/, '') }],
        renderConfiguration: (node) => <StepDelayConfiguration key={node.id} node={node} />,
    },
    exit: {
        type: 'exit',
        icon: () => <IconLeave />,
        color: () => '#4b4b4b',
        getPreviews: (action) => [{ label: action.config.reason || 'End workflow' }],
        renderConfiguration: (node) => <StepExitConfiguration key={node.id} node={node} />,
    },

    random_cohort_branch: {
        type: 'random_cohort_branch',
        icon: () => <IconPercentage />,
        color: (_, isDarkModeOn) => (isDarkModeOn ? '#D6247B' : '#9a004d'),
        getPreviews: (action) => [
            {
                label: `${action.config.cohorts.length} ${action.config.cohorts.length === 1 ? 'cohort' : 'cohorts'}`,
            },
        ],
        renderConfiguration: (node) => <StepRandomCohortBranchConfiguration key={node.id} node={node} />,
    },
    trigger: {
        type: 'trigger',
        icon: () => <IconBolt />,
        color: (_, isDarkModeOn) => (isDarkModeOn ? '#35C46F' : '#005841'),
        getPreviews: getTriggerPreviews,
        renderConfiguration: (node) => <StepTriggerConfiguration key={node.id} node={node} />,
    },
    wait_until_condition: {
        type: 'wait_until_condition',
        icon: () => <IconHourglass />,
        color: () => '#ffaa00',
        getPreviews: (action) => [{ label: `Up to ${action.config.max_wait_duration}` }],
        renderConfiguration: (node) => <StepWaitUntilConditionConfiguration key={node.id} node={node} />,
    },
    wait_until_time_window: {
        type: 'wait_until_time_window',
        icon: () => <IconDay />,
        color: () => '#FF653F',
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
        icon: () => <IconLetter />,
        color: (_, isDarkModeOn) => (isDarkModeOn ? '#2F80FA' : '#2F80FA'),
        getPreviews: (action) => [
            {
                label: action.config.inputs.email?.value?.to?.email
                    ? `To ${action.config.inputs.email.value.to.email}`
                    : 'Email',
            },
        ],
        renderConfiguration: (node) => <StepFunctionConfiguration key={node.id} node={node} />,
    },
    function_sms: {
        type: 'function_sms',
        icon: () => <IconTwilio />,
        color: () => '#f22f46',
        getPreviews: (action) => [
            { label: action.config.inputs.phoneNumber?.value ? `To ${action.config.inputs.phoneNumber.value}` : 'SMS' },
        ],
        renderConfiguration: (node) => <StepFunctionConfiguration key={node.id} node={node} />,
    },
    function_push: {
        type: 'function_push',
        icon: () => <IconNotification />,
        color: (_, isDarkModeOn) => (isDarkModeOn ? '#F8BE2A' : '#F44D01'),
        getPreviews: (action) => [
            {
                label: action.config.inputs.title?.value
                    ? String(action.config.inputs.title.value)
                    : 'Push notification',
            },
        ],
        renderConfiguration: (node) => <StepFunctionConfiguration key={node.id} node={node} />,
    },
    function: {
        type: 'function',
        icon: (action, hogFunctionTemplatesById) => {
            if (action.config.template_id === 'template-email') {
                return <IconLetter />
            }

            if (action.config.template_id === 'template-webhook') {
                return <IconWebhooks />
            }

            if (action.config.template_id === 'template-native-push') {
                return <IconNotification />
            }

            const template = hogFunctionTemplatesById[action.config.template_id]
            return template?.icon_url ? (
                <img className="LemonIcon rounded" src={template.icon_url} alt={template.name} />
            ) : (
                <IconBolt />
            )
        },
        color: (action, isDarkModeOn) => {
            if (action.config.template_id === 'template-email') {
                return isDarkModeOn ? '#2F80FA' : '#2F80FA'
            }

            if (action.config.template_id === 'template-webhook') {
                return isDarkModeOn ? '#B52AD9' : '#6500ae'
            }

            return isDarkModeOn ? '#F8BE2A' : '#F44D01'
        },
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
    if (!builder) {
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
        icon: builder.icon(action, hogFunctionTemplatesById),
        color: builder.color(action, isDarkModeOn),
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
