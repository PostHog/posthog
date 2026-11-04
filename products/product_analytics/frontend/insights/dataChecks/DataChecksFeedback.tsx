import { useActions, useValues } from 'kea'
import { useEffect, useId } from 'react'

import { IconThumbsDown, IconThumbsUp, IconX } from '@posthog/icons'
import { Button, Field, FieldLabel, Text, Textarea } from '@posthog/quill'

import { DATA_CHECKS_FEEDBACK_RATINGS, dataChecksFeedbackLogic } from './dataChecksFeedbackLogic'

const RATINGS = [
    { value: DATA_CHECKS_FEEDBACK_RATINGS.USEFUL, label: 'Useful', icon: <IconThumbsUp /> },
    { value: DATA_CHECKS_FEEDBACK_RATINGS.NOT_USEFUL, label: 'Not useful', icon: <IconThumbsDown /> },
]

export function DataChecksFeedback({ userId }: { userId: string }): JSX.Element | null {
    const questionId = useId()
    const noteId = useId()
    const logic = dataChecksFeedbackLogic({ userId })
    const { survey, visible, shownReported, rating, note, noteSent } = useValues(logic)
    const { reportShown, rate, setNote, submitNote, dismiss } = useActions(logic)

    useEffect(() => {
        if (visible && !shownReported) {
            reportShown()
        }
    }, [visible, shownReported, reportShown])

    if (!visible || !survey) {
        return null
    }

    const [ratingQuestion, noteQuestion] = survey.questions

    return (
        <div className="flex flex-col gap-2 border-t border-(--border) pt-2" data-attr="insight-data-checks-feedback">
            {noteSent ? (
                <Text size={null} variant="muted" role="status">
                    Thanks for your feedback.
                </Text>
            ) : rating ? (
                <>
                    <Field>
                        <FieldLabel htmlFor={noteId}>{noteQuestion?.question}</FieldLabel>
                        <Textarea
                            id={noteId}
                            value={note}
                            onChange={(event) => setNote(event.target.value)}
                            rows={2}
                            maxLength={2000}
                            autoFocus
                            data-attr="insight-data-checks-feedback-detail"
                        />
                    </Field>
                    <Button
                        variant="outline"
                        size="sm"
                        className="self-start"
                        onClick={submitNote}
                        data-attr="insight-data-checks-feedback-submit"
                    >
                        {note.trim() ? 'Send feedback' : 'Done'}
                    </Button>
                </>
            ) : (
                <div className="flex items-center justify-between gap-2">
                    <Text id={questionId} size={null}>
                        {ratingQuestion?.question}
                    </Text>
                    <div className="flex items-center gap-1">
                        <div className="flex items-center gap-1" role="group" aria-labelledby={questionId}>
                            {RATINGS.map(({ value, label, icon }) => (
                                <Button
                                    key={value}
                                    variant="outline"
                                    size="icon-sm"
                                    aria-label={label}
                                    tooltip={label}
                                    onClick={() => rate(value)}
                                    data-attr="insight-data-checks-feedback-answer"
                                    data-feedback-rating={value}
                                >
                                    {icon}
                                </Button>
                            ))}
                        </div>
                        <Button
                            size="icon-sm"
                            aria-label="Dismiss"
                            tooltip="Dismiss"
                            onClick={dismiss}
                            data-attr="insight-data-checks-feedback-dismiss"
                        >
                            <IconX />
                        </Button>
                    </div>
                </div>
            )}
        </div>
    )
}
