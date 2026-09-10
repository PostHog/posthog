import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import { LemonBanner, LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import {
    SourceSteeringModalLogicProps,
    sourceHasLegacyPosture,
    sourceSteeringModalLogic,
} from '../../logics/sourceSteeringModalLogic'
import { SOURCE_STEERING_MAX_LENGTH, SignalSourceConfig } from '../../types'

export interface SourceSteeringModalProps {
    /** Every config row this source's guidance is saved to. See `SourceSteeringModalLogicProps`. */
    sourceConfigs: SignalSourceConfig[]
    /** The roster label of the source being steered, for the modal title. */
    sourceLabel: string
    onClose: () => void
}

export function SourceSteeringModal({ sourceConfigs, sourceLabel, onClose }: SourceSteeringModalProps): JSX.Element {
    const formId = useId()
    const logicProps: SourceSteeringModalLogicProps = { sourceConfigs, onClose }
    const logic = sourceSteeringModalLogic(logicProps)
    const { isSourceSteeringSubmitting, sourceSteeringChanged, sourceSteeringValidationErrors, steeringExamples } =
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
                    {sourceConfigs.some(sourceHasLegacyPosture) && (
                        <LemonBanner type="info">
                            This source only reports records that clearly qualify. Saving here replaces that with what
                            you write below.
                        </LemonBanner>
                    )}
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
                            {steeringExamples.map((example) => (
                                <LemonButton
                                    key={example.label}
                                    type="secondary"
                                    size="xsmall"
                                    tooltip={example.line}
                                    // A string tooltip would otherwise become the whole accessible
                                    // name, hiding the visible label from speech control.
                                    aria-label={`${example.label}: adds "${example.line}"`}
                                    onClick={() => setSourceSteeringValue('steering', example.result)}
                                    disabledReason={
                                        isSourceSteeringSubmitting
                                            ? 'Saving'
                                            : !example.fits
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
