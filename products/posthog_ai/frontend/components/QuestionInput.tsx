import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef, useState } from 'react'

import { IconChat } from '@posthog/icons'
import { LemonTag, Spinner } from '@posthog/lemon-ui'

import type { MultiQuestionFormQuestion } from '~/queries/schema/schema-assistant-messages'

import { runStreamLogic } from '../logics/runStreamLogic'
import { deriveQuestionOptionId, type AgentQuestion } from '../policy/questionUtils'
import type { PermissionRequestRecord } from '../types/streamTypes'
import { QuestionField } from './QuestionField'

interface QuestionInputProps {
    streamKey: string
    request: PermissionRequestRecord
}

/** Adapt a sandbox question onto the `MultiQuestionFormQuestion` shape `QuestionField` renders. */
function toFormQuestion(question: AgentQuestion, index: number): MultiQuestionFormQuestion {
    return {
        id: String(index),
        title: question.header ?? 'Question',
        question: question.question,
        type: question.multiSelect ? 'multi_select' : 'select',
        options: question.options.map((option) => ({ value: option.label, description: option.description })),
        allow_custom_answer: true,
    }
}

function selectedLabels(answer: string | string[] | undefined): string[] {
    if (Array.isArray(answer)) {
        return answer
    }
    return answer ? [answer] : []
}

/**
 * Interactive input-area overlay for an `AskUserQuestion` on a sandbox conversation. The agent (Twig)
 * routes questions through the ACP permission framework, so this rides the same `pendingPermissionRequest`
 * rails as `PermissionInput` but renders the question(s) instead of an approve/decline card.
 *
 * It reuses the LangGraph `QuestionField` (and therefore `OptionSelector` / `LemonCheckbox`) for the
 * options, and mirrors `MultiQuestionFormInput`'s flow: single-select answers advance on pick,
 * multi-select accumulates behind a Next/Submit button, and the footer label flips to "Submit" on the
 * last question. On submit it replies via `respondToPermission` with the answers keyed by question
 * text — the agent reads `_meta.answers`; `optionId` only has to be a valid offered option (derived
 * from the first question's selection). `respondingToPermission` drives the loading / double-submit guard.
 */
export function QuestionInput({ streamKey, request }: QuestionInputProps): JSX.Element | null {
    const boundLogic = runStreamLogic({ streamKey })
    const { respondToPermission } = useActions(boundLogic)
    const { respondingToPermission } = useValues(boundLogic)

    // Stable reference so the memoized callbacks below don't re-evaluate every render.
    const questions = useMemo(() => request.questions ?? [], [request.questions])

    const [currentIndex, setCurrentIndex] = useState(0)
    const [answers, setAnswers] = useState<Record<number, string | string[]>>({})
    const answersRef = useRef(answers)
    answersRef.current = answers

    const submit = useCallback(
        (finalAnswers: Record<number, string | string[]>) => {
            const answerMap: Record<string, string> = {}
            for (let index = 0; index < questions.length; index++) {
                const labels = selectedLabels(finalAnswers[index])
                if (labels.length) {
                    answerMap[questions[index].question] = labels.join(', ')
                }
            }
            // Options only exist on the wire for the first question, so optionId / customInput derive
            // from it; the answers map carries the rest for the agent.
            const firstQuestion = questions[0]
            const firstLabels = selectedLabels(finalAnswers[0])
            const firstOptionLabels = new Set(firstQuestion.options.map((option) => option.label))
            respondToPermission({
                requestId: request.requestId,
                optionId: deriveQuestionOptionId(firstQuestion, firstLabels),
                answers: answerMap,
                customInput: firstLabels.find((label) => !firstOptionLabels.has(label)),
            })
        },
        [questions, request.requestId, respondToPermission]
    )

    const advanceOrSubmit = useCallback(
        (updatedAnswers: Record<number, string | string[]>) => {
            if (currentIndex < questions.length - 1) {
                setCurrentIndex(currentIndex + 1)
            } else {
                submit(updatedAnswers)
            }
        },
        [currentIndex, questions.length, submit]
    )

    const handleAnswer = useCallback(
        (value: string | string[] | null) => {
            if (respondingToPermission) {
                return
            }
            if (value === null) {
                const cleared = { ...answersRef.current }
                delete cleared[currentIndex]
                setAnswers(cleared)
                answersRef.current = cleared
                return
            }
            const updated = { ...answersRef.current, [currentIndex]: value }
            setAnswers(updated)
            answersRef.current = updated
            advanceOrSubmit(updated)
        },
        [advanceOrSubmit, currentIndex, respondingToPermission]
    )

    const handleMultiSelectChange = useCallback(
        (value: string[]) => {
            const updated = { ...answersRef.current, [currentIndex]: value }
            setAnswers(updated)
            answersRef.current = updated
        },
        [currentIndex]
    )

    const handleMultiSelectSubmit = useCallback(() => {
        if (respondingToPermission) {
            return
        }
        advanceOrSubmit(answersRef.current)
    }, [advanceOrSubmit, respondingToPermission])

    // The dispatcher only mounts this when `questions` is non-empty; keep the guard for type safety.
    const question = questions[currentIndex]
    if (!question) {
        return null
    }

    if (respondingToPermission) {
        return (
            <div className="flex items-center gap-2 text-muted p-3">
                <Spinner className="size-4" />
                <span>Sending response…</span>
            </div>
        )
    }

    const isLast = currentIndex === questions.length - 1

    return (
        <div className="flex flex-col gap-2 p-3">
            <div className="flex items-center gap-2 text-sm">
                <IconChat className="text-muted size-4" />
                <LemonTag size="small" type="muted">
                    {question.header ?? 'Question'}
                </LemonTag>
                {questions.length > 1 && (
                    <span className="text-muted text-xs">
                        {currentIndex + 1}/{questions.length}
                    </span>
                )}
            </div>
            <div className="font-medium text-sm">{question.question}</div>
            <QuestionField
                key={currentIndex}
                question={toFormQuestion(question, currentIndex)}
                value={answers[currentIndex]}
                onAnswer={handleAnswer}
                onChange={handleMultiSelectChange}
                onSubmit={handleMultiSelectSubmit}
                submitLabel={isLast ? 'Submit' : 'Next'}
            />
        </div>
    )
}
