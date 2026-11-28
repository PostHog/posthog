import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { MAX_STEPS } from '../journeySteps'
import { userJourneyFormLogic } from '../userJourneyFormLogic'
import { JourneyStepEditor } from './JourneyStepEditor'

export function JourneyStepsEditor({ id }: { id: string }): JSX.Element {
    const { draft, errors } = useValues(userJourneyFormLogic({ id }))
    const { addStep } = useActions(userJourneyFormLogic({ id }))
    const atLimit = draft.steps.length >= MAX_STEPS
    const limitReason = atLimit ? `A journey can have at most ${MAX_STEPS} steps` : undefined

    return (
        <LemonField.Pure
            label="Steps"
            help="A session completes the journey when it does every step in this order."
            error={errors.steps}
        >
            <div className="flex flex-col gap-2">
                {draft.steps.map((step, index) => (
                    <JourneyStepEditor
                        key={step.key}
                        id={id}
                        step={step}
                        index={index}
                        stepCount={draft.steps.length}
                    />
                ))}
                <div className="flex gap-2 flex-wrap">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={() => addStep('pageview')}
                        disabledReason={limitReason}
                        data-attr="user-journey-add-pageview-step"
                    >
                        Add pageview
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={() => addStep('element_click')}
                        disabledReason={limitReason}
                        data-attr="user-journey-add-click-step"
                    >
                        Add click
                    </LemonButton>
                </div>
            </div>
        </LemonField.Pure>
    )
}
