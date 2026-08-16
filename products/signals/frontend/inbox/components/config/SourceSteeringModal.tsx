import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { SourceSteeringModalLogicProps, sourceSteeringModalLogic } from '../../logics/sourceSteeringModalLogic'
import { SOURCE_STEERING_MAX_LENGTH, SignalSourceConfig } from '../../types'

// LemonRadio keys must be React keys, so the boolean `default_not_actionable` postures get names.
const LENIENT = 'lenient'
const STRICT = 'strict'

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
    const { isSourceSteeringSubmitting, sourceSteeringChanged, sourceSteeringValidationErrors } = useValues(logic)

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
    // Freeze the fields while the save is in flight: the submit already captured the form values,
    // so edits made during the request would be silently dropped by a success that closes the modal.
    const savingReason = isSourceSteeringSubmitting ? 'Saving your rules' : undefined

    return (
        <LemonModal
            isOpen
            onClose={handleClose}
            title={`Steering rules for ${sourceLabel}`}
            description="Most records from this source count as actionable and can become reports. Your rules change what gets kept. They apply from the next sync and don't remove anything already in your inbox."
            width={560}
            hasUnsavedInput={sourceSteeringChanged}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={handleClose}
                        disabledReason={isSourceSteeringSubmitting ? 'Saving your rules' : undefined}
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
                        Save rules
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
                <div className="flex flex-col gap-4">
                    <LemonField name="defaultNotActionable" label="Default behavior">
                        {({ value, onChange }) => (
                            <LemonRadio
                                aria-label="Default behavior"
                                value={value ? STRICT : LENIENT}
                                onChange={(posture: string) => onChange(posture === STRICT)}
                                options={[
                                    {
                                        value: LENIENT,
                                        label: 'Include everything except what I list',
                                        description: 'When in doubt, a record is kept.',
                                        disabledReason: savingReason,
                                    },
                                    {
                                        value: STRICT,
                                        label: "Only include what's clearly actionable",
                                        description: 'When in doubt, a record is skipped.',
                                        disabledReason: savingReason,
                                    },
                                ]}
                            />
                        )}
                    </LemonField>
                    <LemonField
                        name="steering"
                        label="Your rules for this source"
                        help="Include, exclude, or prioritize. Plain language works. Leave it empty to keep only the default behavior above."
                    >
                        <LemonTextArea
                            minRows={4}
                            maxRows={10}
                            maxLength={SOURCE_STEERING_MAX_LENGTH}
                            placeholder="Ignore issues labeled chore or internal. Anything mentioning billing is always actionable."
                            disabled={isSourceSteeringSubmitting}
                            data-attr="signal-source-steering-rules"
                        />
                    </LemonField>
                </div>
            </Form>
        </LemonModal>
    )
}
