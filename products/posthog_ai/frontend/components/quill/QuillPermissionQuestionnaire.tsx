import { type ReactNode, useState } from 'react'

import {
    Button,
    Card,
    CardContent,
    CardFooter,
    CardHeader,
    CardTitle,
    Questionnaire,
    QuestionnaireActions,
    QuestionnaireChoice,
    QuestionnaireChoiceDescription,
    QuestionnaireChoices,
    QuestionnaireError,
    QuestionnaireInput,
    QuestionnaireItem,
    QuestionnaireSubmit,
    QuestionnaireTitle,
} from '@posthog/quill-primitives'

import {
    FEEDBACK_PLACEHOLDER,
    isFeedbackOption,
    optionRowLabel,
    optionSublabel,
} from '../../policy/permissionOptionCopy'
import type { ApprovalCardOption } from '../../policy/permissionUtils'

const ANSWER_NAME = 'permission'

type PermissionAnswer = { kind: 'choice'; optionId: string } | { kind: 'note'; optionId: string; text: string }

export interface QuillPermissionQuestionnaireProps {
    headline: ReactNode
    evidence: ReactNode
    options: ApprovalCardOption[]
    responding: boolean
    onRespond: (optionId: string, customInput?: string) => void
}

/**
 * The note row answers a decline that relays feedback, so that decline's own choice only has to say "No".
 * Without that split the choice and the note row both read as "tell the agent what to do differently".
 * With several such declines, each keeps its own label so the choices stay distinct.
 */
function choiceCopy(
    option: ApprovalCardOption,
    soleFeedbackOption: boolean
): { label: string; description: string | null } {
    if (option.supportsFeedback && soleFeedbackOption) {
        return { label: 'No', description: 'Stops this turn.' }
    }
    return { label: optionRowLabel(option), description: optionSublabel(option) }
}

export function QuillPermissionQuestionnaire({
    headline,
    evidence,
    options,
    responding,
    onRespond,
}: QuillPermissionQuestionnaireProps): JSX.Element {
    const [answer, setAnswer] = useState<PermissionAnswer | null>(null)
    const feedbackOptions = options.filter(isFeedbackOption)
    const soleFeedbackOption = feedbackOptions.length === 1
    const choiceOptions = options.filter((option) => !option.requiresFeedback)

    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle>{headline}</CardTitle>
            </CardHeader>
            {/* `contents` keeps the card's content and footer in the card's own layout while the form still wraps the submit. */}
            <Questionnaire
                className="contents"
                items={[{ name: ANSWER_NAME, required: true }]}
                shortcuts="numbers"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (responding || !answer) {
                        return
                    }
                    if (answer.kind === 'note') {
                        onRespond(answer.optionId, answer.text)
                    } else {
                        onRespond(answer.optionId)
                    }
                }}
            >
                <CardContent className="flex flex-col gap-3">
                    {evidence}
                    <QuestionnaireItem name={ANSWER_NAME} required>
                        <QuestionnaireTitle className="sr-only">Allow this?</QuestionnaireTitle>
                        <QuestionnaireChoices>
                            {choiceOptions.map((option) => {
                                const { label, description } = choiceCopy(option, soleFeedbackOption)
                                return (
                                    <QuestionnaireChoice
                                        key={option.optionId}
                                        value={option.optionId}
                                        onChange={(event) =>
                                            event.target.checked &&
                                            setAnswer({ kind: 'choice', optionId: option.optionId })
                                        }
                                    >
                                        {label}
                                        {description && (
                                            <QuestionnaireChoiceDescription>
                                                {description}
                                            </QuestionnaireChoiceDescription>
                                        )}
                                    </QuestionnaireChoice>
                                )
                            })}
                            {feedbackOptions.map((option) => {
                                const noteLabel = soleFeedbackOption ? FEEDBACK_PLACEHOLDER : optionRowLabel(option)
                                return (
                                    <QuestionnaireInput
                                        key={option.optionId}
                                        aria-label={noteLabel}
                                        placeholder={noteLabel}
                                        onChange={(event) => {
                                            const text = event.target.value.trim()
                                            setAnswer((current) =>
                                                text
                                                    ? { kind: 'note', optionId: option.optionId, text }
                                                    : current?.kind === 'note' && current.optionId === option.optionId
                                                      ? null
                                                      : current
                                            )
                                        }}
                                    />
                                )
                            })}
                        </QuestionnaireChoices>
                        <QuestionnaireError />
                    </QuestionnaireItem>
                </CardContent>
                <CardFooter>
                    <QuestionnaireActions className="w-full">
                        <QuestionnaireSubmit render={<Button variant="primary" loading={responding} />}>
                            Send
                        </QuestionnaireSubmit>
                    </QuestionnaireActions>
                </CardFooter>
            </Questionnaire>
        </Card>
    )
}
