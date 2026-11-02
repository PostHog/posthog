import { ThumbsDown, ThumbsUp, X } from 'lucide-react'
import { type ReactElement, useEffect, useId, useState } from 'react'

import { Button, Field, FieldLabel, Text, Textarea } from '@posthog/quill'

import { capture, isAnalyticsEnabled, newId } from '../analytics/posthog'

// An API survey in the PostHog project that receives the app's analytics. The app sends the responses itself.
const SURVEY_ID = '01a18c51-4f07-0000-03ff-d05744424486'
const RATING_QUESTION_ID = 'ea2206c2-1e43-41f8-ba87-86d6281ed76d'
const NOTE_QUESTION_ID = '6631e694-32f6-4add-897c-a23029a4d284'
const SURVEY_PROPERTIES = { $survey_id: SURVEY_ID, $survey_name: 'Explain chart usefulness' }

// A two-point thumbs rating stores 1 for thumbs up and 2 for thumbs down.
const RATINGS = [
    { value: '1', label: 'Useful', icon: <ThumbsUp className="size-3.5" /> },
    { value: '2', label: 'Not useful', icon: <ThumbsDown className="size-3.5" /> },
]

export function ExplainChartFeedback(): ReactElement | null {
    const questionId = useId()
    const noteId = useId()
    const [enabled] = useState(isAnalyticsEnabled)
    const [submissionId] = useState(newId)
    const [rating, setRating] = useState<string | null>(null)
    const [note, setNote] = useState('')
    const [state, setState] = useState<'asking' | 'sent' | 'dismissed'>('asking')

    useEffect(() => {
        if (enabled) {
            capture('survey shown', SURVEY_PROPERTIES)
        }
    }, [enabled])

    if (!enabled || state === 'dismissed') {
        return null
    }

    const send = (value: string, completed: boolean): void => {
        const trimmed = note.trim()
        capture('survey sent', {
            ...SURVEY_PROPERTIES,
            $survey_submission_id: submissionId,
            $survey_completed: completed,
            [`$survey_response_${RATING_QUESTION_ID}`]: value,
            ...(completed && trimmed ? { [`$survey_response_${NOTE_QUESTION_ID}`]: trimmed } : {}),
        })
    }

    const rate = (value: string): void => {
        setRating(value)
        send(value, false)
    }

    const dismiss = (): void => {
        capture('survey dismissed', SURVEY_PROPERTIES)
        setState('dismissed')
    }

    return (
        <div className="mt-3 flex flex-col gap-2 border-t border-border pt-3" data-attr="explain-chart-feedback">
            {state === 'sent' ? (
                <Text size="sm" variant="muted" role="status">
                    Thanks for your feedback.
                </Text>
            ) : rating ? (
                <>
                    <Field>
                        <FieldLabel htmlFor={noteId}>Any other feedback?</FieldLabel>
                        <Textarea
                            id={noteId}
                            value={note}
                            onChange={(event) => setNote(event.target.value)}
                            rows={2}
                            maxLength={2000}
                            autoFocus
                            data-attr="explain-chart-feedback-detail"
                        />
                    </Field>
                    <Button
                        variant="outline"
                        size="sm"
                        className="self-start"
                        onClick={() => {
                            send(rating, true)
                            setState('sent')
                        }}
                        data-attr="explain-chart-feedback-submit"
                    >
                        {note.trim() ? 'Send feedback' : 'Done'}
                    </Button>
                </>
            ) : (
                <div className="flex items-center justify-between gap-2">
                    <Text id={questionId} size="sm">
                        Was this explanation useful?
                    </Text>
                    <div className="flex items-center gap-1">
                        <div className="flex items-center gap-1" role="group" aria-labelledby={questionId}>
                            {RATINGS.map(({ value, label, icon }) => (
                                <Button
                                    key={value}
                                    variant="outline"
                                    size="icon-sm"
                                    aria-label={label}
                                    title={label}
                                    onClick={() => rate(value)}
                                    data-attr="explain-chart-feedback-answer"
                                >
                                    {icon}
                                </Button>
                            ))}
                        </div>
                        <Button
                            size="icon-sm"
                            aria-label="Dismiss"
                            title="Dismiss"
                            onClick={dismiss}
                            data-attr="explain-chart-feedback-dismiss"
                        >
                            <X className="size-3.5" />
                        </Button>
                    </div>
                </div>
            )}
        </div>
    )
}
