import { Node } from '@xyflow/react'
import { useValues } from 'kea'
import { useMemo } from 'react'

import {
    IconBolt,
    IconClock,
    IconDay,
    IconDecisionTree,
    IconHourglass,
    IconLeave,
    IconLetter,
    IconPercentage,
} from '@posthog/icons'

import { IconSlack, IconTwilio } from 'lib/lemon-ui/icons'

import { HogFunctionTemplateType } from '~/types'

import { campaignLogic } from '../../campaignLogic'
import { HogFlowAction } from '../types'
import { StepConditionalBranchConfiguration } from './StepConditionalBranch'
import { StepDelayConfiguration } from './StepDelay'
import { StepExitConfiguration } from './StepExit'
import { StepFunctionConfiguration } from './StepFunction'
import { StepRandomCohortBranchConfiguration } from './StepRandomCohortBranch'
import { StepTriggerConfiguration } from './StepTrigger'
import { StepWaitUntilConditionConfiguration } from './StepWaitUntilCondition'
import { StepWaitUntilTimeWindowConfiguration } from './StepWaitUntilTimeWindow'

type HogFlowStepBuilder<T extends HogFlowAction['type']> = {
    type: T
    icon: (
        action: Extract<HogFlowAction, { type: T }>,
        hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
    ) => JSX.Element
    color: (
        action: Extract<HogFlowAction, { type: T }>,
        hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
    ) => string
    renderConfiguration: (node: Node<Extract<HogFlowAction, { type: T }>>) => JSX.Element
}

type HogFlowStep<T extends HogFlowAction['type']> = {
    type: T
    icon: JSX.Element
    color: string
    renderConfiguration: (node: Node<Extract<HogFlowAction, { type: T }>>) => JSX.Element
}

const HogFlowStepConfigs: Partial<{
    [K in HogFlowAction['type']]: HogFlowStepBuilder<K>
}> = {
    conditional_branch: {
        type: 'conditional_branch',
        icon: () => <IconDecisionTree />,
        color: () => '#005841',
        renderConfiguration: (node) => <StepConditionalBranchConfiguration node={node} />,
    },
    delay: {
        type: 'delay',
        icon: () => <IconClock />,
        color: () => '#a20031',
        renderConfiguration: (node) => <StepDelayConfiguration node={node} />,
    },
    exit: {
        type: 'exit',
        icon: () => <IconLeave />,
        color: () => '#4b4b4b',
        renderConfiguration: (node) => <StepExitConfiguration node={node} />,
    },
    function_email: {
        type: 'function_email',
        icon: () => <IconLetter />,
        color: () => '#005841',
        renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    },
    function_slack: {
        type: 'function_slack',
        icon: () => <IconSlack />,
        color: () => '#4A154B',
        renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    },
    function_sms: {
        type: 'function_sms',
        icon: () => <IconTwilio />,
        color: () => '#f22f46',
        renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    },
    // function_webhook: {
    //     type: 'function_webhook',
    //     icon: () => <IconWebhooks />,
    //     color: () => '#6500ae',
    //     renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    // },
    random_cohort_branch: {
        type: 'random_cohort_branch',
        icon: () => <IconPercentage />,
        color: () => '#9a004d',
        renderConfiguration: (node) => <StepRandomCohortBranchConfiguration node={node} />,
    },
    trigger: {
        type: 'trigger',
        icon: () => <IconBolt />,
        color: () => '#005841',
        renderConfiguration: (node) => <StepTriggerConfiguration node={node} />,
    },
    wait_until_condition: {
        type: 'wait_until_condition',
        icon: () => <IconHourglass />,
        color: () => '#ffaa00',
        renderConfiguration: (node) => <StepWaitUntilConditionConfiguration node={node} />,
    },
    wait_until_time_window: {
        type: 'wait_until_time_window',
        icon: () => <IconDay />,
        color: () => '#005841',
        renderConfiguration: (node) => <StepWaitUntilTimeWindowConfiguration node={node} />,
    },

    function: {
        type: 'function',
        icon: (action, hogFunctionTemplatesById) => {
            if (action.config.template_id === 'template-email') {
                return <IconLetter />
            }

            const template = hogFunctionTemplatesById[action.config.template_id]
            return template?.icon_url ? (
                <img className="LemonIcon" src={template.icon_url} alt={template.name} />
            ) : (
                <IconBolt />
            )
        },
        color: () => '#005841',
        renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    },
} as const

// Type-safe accessor that preserves the key type
export function getHogFlowStep<T extends HogFlowAction['type']>(
    action: Extract<HogFlowAction, { type: T }>,
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
): HogFlowStep<T> | undefined {
    const type = action.type
    const builder = HogFlowStepConfigs[type]
    if (!builder) {
        return undefined
    }
    return {
        type,
        icon: builder.icon(action, hogFunctionTemplatesById),
        color: builder.color(action, hogFunctionTemplatesById),
        renderConfiguration: builder.renderConfiguration,
    }
}

export function useHogFlowStep<T extends HogFlowAction['type']>(
    action?: Extract<HogFlowAction, { type: T }>
): HogFlowStep<T> | undefined {
    const { hogFunctionTemplatesById } = useValues(campaignLogic)

    return useMemo(() => {
        if (!action) {
            return undefined
        }
        return getHogFlowStep(action, hogFunctionTemplatesById)
    }, [action, hogFunctionTemplatesById])
}
