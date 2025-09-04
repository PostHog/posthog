import { IconBolt } from '@posthog/icons'

import { StepFunctionConfiguration } from './StepFunction'
import { HogFlowStep } from './types'

export const StepFunctionPostHogCapture: HogFlowStep<'function_posthog_capture'> = {
    type: 'function_posthog_capture',
    name: 'Capture event',
    description: 'Capture an event to PostHog.',
    icon: <IconBolt className="text-[#005841]" />,
    color: '#005841',
    renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Capture event',
                description: '',
                type: 'function_posthog_capture',
                on_error: 'continue',
                config: {
                    template_id: 'template-posthog-capture',
                    inputs: {},
                },
            },
        }
    },
}

export const StepFunctionPostHogGroupIdentify: HogFlowStep<'function_posthog_group_identify'> = {
    type: 'function_posthog_group_identify',
    name: 'Set group properties',
    description: 'Set properties of a group in PostHog.',
    icon: <IconBolt className="text-[#005841]" />,
    color: '#005841',
    renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Set group properties',
                description: '',
                type: 'function_posthog_group_identify',
                on_error: 'continue',
                config: {
                    template_id: 'template-posthog-group-identify',
                    inputs: {},
                },
            },
        }
    },
}

export const StepFunctionPostHogUpdatePersonProperties: HogFlowStep<'function_posthog_update_person_properties'> = {
    type: 'function_posthog_update_person_properties',
    name: 'Update person properties',
    description: 'Update properties of a person in PostHog.',
    icon: <IconBolt className="text-[#005841]" />,
    color: '#005841',
    renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Update person properties',
                description: '',
                type: 'function_posthog_update_person_properties',
                on_error: 'continue',
                config: {
                    template_id: 'template-posthog-update-person-properties',
                    inputs: {},
                },
            },
        }
    },
}
