import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { SourceSteeringModalLogicProps, sourceSteeringModalLogic } from '../../logics/sourceSteeringModalLogic'
import { SOURCE_STEERING_MAX_LENGTH, SignalSourceConfig } from '../../types'

// Chips carry a short label so they stay on one line in a narrow modal: LemonButton neither
// shrinks nor wraps, so a full-sentence label overflows instead of wrapping inside the modal.
const EXAMPLES: { label: string; line: string }[] = [
    { label: 'Skip chores', line: 'Skip anything labeled chore, internal, or dependencies.' },
    { label: 'Billing only', line: 'Only report issues about billing, checkout, or payments.' },
    { label: 'Paying customers', line: 'Anything a paying customer opened is worth reporting.' },
]

export interface SourceSteeringModalProps {
    sourceConfig: SignalSourceConfig
    /** The roster label of the source being steered, for the modal title. */
    sourceLabel: string
    onClose: () => void
}

export function SourceSteeringModal({ sourceConfig, sourceLabel, onClose }: SourceSteeringModalProps): JSX.Element {
    const formId = useId()
    const logicProps: SourceSteeringModalLogicProps = { sourceConfig, onClose }
    const logic = sourceSteeringModalLogic(logicProps)
    const { isSourceSteeringSubmitting, sourceSteeringChanged, sourceSteeringValidationErrors, sourceSteering } =
        useValues(logic)
    const { setSourceSteeringValue } = useActions(logic)

    const handleClose = (): void => {
        if (isSourceSteeringSubmitting) {
            return
        }
        onClose()
    }

    const steeringError =
        typeof sourceSteeringValidationErrors.steering === 'string'
            ? sourceSteeringValidationErrors.steering
            : undefined

    // The textarea's maxLength only bounds typing, so an example appended programmatically could
    // push the value over the cap and leave the form unsavable with no edit of the user's own.
    const exampleResult = (line: string): string => {
        const current = sourceSteering.steering.trimEnd()
        return current ? `${current}\n${line}` : line
    }
    const appendExample = (line: string): void => setSourceSteeringValue('steering', exampleResult(line))

    return (
        <LemonModal
            isOpen
            onClose={handleClose}
            title={`Guidance for ${sourceLabel}`}
            description={`Tell the agent what matters and what to skip in ${sourceLabel}. It reads this when deciding what turns into a report. Leave it empty and it uses its own judgment.`}
            width={560}
            hasUnsavedInput={sourceSteeringChanged}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={handleClose}
                        disabledReason={isSourceSteeringSubmitting ? 'Saving' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        form={formId}
                        htmlType="submit"
                        loading={isSourceSteeringSubmitting}
                        disabledReason={steeringError}
                        data-attr="signal-source-steering-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={sourceSteeringModalLogic}
                props={logicProps}
                formKey="sourceSteering"
                id={formId}
                enableFormOnSubmit
            >
                <div className="flex flex-col gap-3">
                    <LemonField
                        name="steering"
                        help="Applies from the next sync. Nothing already in your inbox changes."
                    >
                        <LemonTextArea
                            minRows={4}
                            maxRows={10}
                            maxLength={SOURCE_STEERING_MAX_LENGTH}
                            // The field has no visible label by design, so name it for screen readers.
                            aria-label={`Guidance for ${sourceLabel}`}
                            placeholder="Write it like a note to a teammate."
                            disabled={isSourceSteeringSubmitting}
                            data-attr="signal-source-steering-rules"
                        />
                    </LemonField>
                    <div className="flex flex-col gap-1">
                        <span className="text-xs text-secondary">Need a starting point? Click one to add it.</span>
                        <div className="flex flex-wrap gap-1">
                            {EXAMPLES.map((example) => (
                                <LemonButton
                                    key={example.label}
                                    type="secondary"
                                    size="xsmall"
                                    tooltip={example.line}
                                    onClick={() => appendExample(example.line)}
                                    disabledReason={
                                        isSourceSteeringSubmitting
                                            ? 'Saving'
                                            : exampleResult(example.line).length > SOURCE_STEERING_MAX_LENGTH
                                              ? "This example won't fit in what you've written"
                                              : undefined
                                    }
                                >
                                    {example.label}
                                </LemonButton>
                            ))}
                        </div>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
