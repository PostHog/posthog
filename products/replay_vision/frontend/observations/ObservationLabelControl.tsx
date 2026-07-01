import { useActions, useValues } from 'kea'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { replayObservationLogic } from './replayObservationLogic'

/**
 * Lets the user mark whether the scanner scored this session correctly and, when wrong, leave feedback.
 * These labels are gathered later to improve the scanner prompt.
 */
export function ObservationLabelControl({ observationId }: { observationId: string }): JSX.Element {
    const logic = replayObservationLogic({ id: observationId })
    const { observation, labelSaving, feedbackDraft } = useValues(logic)
    const { setLabel, clearLabel, setFeedbackDraft } = useActions(logic)

    const myLabel = observation?.my_label ?? null
    const labeledIncorrect = myLabel?.is_correct === false

    return (
        <div className="border rounded p-3 bg-surface-primary space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium">Did the scanner get this right?</span>
                <div className="flex items-center gap-1">
                    <LemonButton
                        size="xsmall"
                        type={myLabel?.is_correct === true ? 'primary' : 'secondary'}
                        icon={<IconCheck />}
                        loading={labelSaving}
                        onClick={() => setLabel(true, '')}
                        data-attr="replay-vision-label-correct"
                    >
                        Correct
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        type={labeledIncorrect ? 'primary' : 'secondary'}
                        icon={<IconX />}
                        loading={labelSaving}
                        onClick={() => setLabel(false, feedbackDraft)}
                        data-attr="replay-vision-label-incorrect"
                    >
                        Incorrect
                    </LemonButton>
                    {myLabel && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => clearLabel()}
                            disabledReason={labelSaving ? 'Saving…' : undefined}
                        >
                            Clear
                        </LemonButton>
                    )}
                </div>
            </div>
            {labeledIncorrect && (
                <div className="space-y-1">
                    <LemonTextArea
                        placeholder="What should it have concluded, and why? This feedback is used to improve the prompt."
                        value={feedbackDraft}
                        onChange={setFeedbackDraft}
                        minRows={2}
                        data-attr="replay-vision-label-feedback"
                    />
                    <div className="flex justify-end">
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            loading={labelSaving}
                            onClick={() => setLabel(false, feedbackDraft)}
                            disabledReason={
                                feedbackDraft === (myLabel?.feedback ?? '') ? 'No changes to save' : undefined
                            }
                        >
                            Save feedback
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
