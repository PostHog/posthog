import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonBadge } from 'lib/lemon-ui/LemonBadge'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { JourneyStepDraft, JourneyStepType, MIN_STEPS, URL_MATCHING_OPTIONS } from '../journeySteps'
import { userJourneyFormLogic } from '../userJourneyFormLogic'

const STEP_TYPE_OPTIONS: { value: JourneyStepType; label: string }[] = [
    { value: 'pageview', label: 'Pageview' },
    { value: 'element_click', label: 'Click' },
]

export interface JourneyStepEditorProps {
    id: string
    step: JourneyStepDraft
    index: number
    stepCount: number
}

export function JourneyStepEditor({ id, step, index, stepCount }: JourneyStepEditorProps): JSX.Element {
    const { errors } = useValues(userJourneyFormLogic({ id }))
    const { updateStep, moveStep, removeStep } = useActions(userJourneyFormLogic({ id }))
    const errorFor = (field: string): string | undefined => errors[`steps.${index}.${field}`]
    const stepNumber = index + 1

    return (
        <div className="border rounded bg-surface-primary p-3 flex flex-col gap-3" data-attr="user-journey-step-editor">
            <div className="flex items-center gap-2 flex-wrap">
                <LemonBadge.Number count={stepNumber} status="muted" size="medium" maxDigits={2} />
                <LemonSegmentedButton
                    size="small"
                    value={step.type}
                    options={STEP_TYPE_OPTIONS}
                    onChange={(type) => updateStep(step.key, { type })}
                />
                <div className="flex-1" />
                <LemonButton
                    size="small"
                    icon={<IconArrowUp />}
                    tooltip="Move up"
                    aria-label={`Move step ${stepNumber} up`}
                    disabledReason={index === 0 ? 'This is the first step' : undefined}
                    onClick={() => moveStep(step.key, -1)}
                    data-attr="user-journey-step-move-up"
                />
                <LemonButton
                    size="small"
                    icon={<IconArrowDown />}
                    tooltip="Move down"
                    aria-label={`Move step ${stepNumber} down`}
                    disabledReason={index === stepCount - 1 ? 'This is the last step' : undefined}
                    onClick={() => moveStep(step.key, 1)}
                    data-attr="user-journey-step-move-down"
                />
                <LemonButton
                    size="small"
                    status="danger"
                    icon={<IconTrash />}
                    tooltip="Remove step"
                    aria-label={`Remove step ${stepNumber}`}
                    disabledReason={stepCount <= MIN_STEPS ? `A journey needs at least ${MIN_STEPS} steps` : undefined}
                    onClick={() => removeStep(step.key)}
                    data-attr="user-journey-step-remove"
                />
            </div>

            {step.type === 'element_click' ? (
                <>
                    <LemonField.Pure
                        label="CSS selector"
                        error={errorFor('selector')}
                        help="Matches the clicked element, for example button.signup or #checkout."
                    >
                        <LemonInput
                            value={step.selector}
                            onChange={(selector) => updateStep(step.key, { selector })}
                            placeholder="button.signup"
                            className="font-mono"
                            data-attr="user-journey-step-selector"
                        />
                    </LemonField.Pure>
                    <div className="grid grid-cols-1 @min-[36rem]/main-content:grid-cols-2 gap-3">
                        <LemonField.Pure
                            label="Element text"
                            showOptional
                            error={errorFor('text')}
                            help="Leave empty to match any text."
                        >
                            <LemonInput
                                value={step.text}
                                onChange={(text) => updateStep(step.key, { text })}
                                placeholder="Sign up"
                            />
                        </LemonField.Pure>
                        <LemonField.Pure
                            label="Link target"
                            showOptional
                            error={errorFor('href')}
                            help="Leave empty to match any link."
                        >
                            <LemonInput
                                value={step.href}
                                onChange={(href) => updateStep(step.key, { href })}
                                placeholder="/signup"
                            />
                        </LemonField.Pure>
                    </div>
                    <LemonField.Pure
                        label="Page"
                        showOptional
                        error={errorFor('url')}
                        help="Leave empty to count the click on any page."
                    >
                        <StepUrlInput step={step} id={id} placeholder="https://example.com/pricing" />
                    </LemonField.Pure>
                </>
            ) : (
                <LemonField.Pure label="Page" error={errorFor('url')}>
                    <StepUrlInput step={step} id={id} placeholder="https://example.com/pricing" />
                </LemonField.Pure>
            )}
        </div>
    )
}

function StepUrlInput({
    id,
    step,
    placeholder,
}: {
    id: string
    step: JourneyStepDraft
    placeholder: string
}): JSX.Element {
    const { updateStep } = useActions(userJourneyFormLogic({ id }))
    return (
        <div className="flex gap-2 flex-wrap">
            <LemonSelect
                size="small"
                value={step.url_matching}
                options={URL_MATCHING_OPTIONS}
                onChange={(url_matching) => updateStep(step.key, { url_matching })}
                dropdownMatchSelectWidth={false}
            />
            <LemonInput
                className="flex-1 min-w-40"
                value={step.url}
                onChange={(url) => updateStep(step.key, { url })}
                placeholder={placeholder}
                data-attr="user-journey-step-url"
            />
        </div>
    )
}
