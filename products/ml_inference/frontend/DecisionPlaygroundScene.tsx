import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonLabel,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { DecisionAnswerCell } from './DecisionAnswerCell'
import {
    PlaygroundOption,
    PlaygroundQuestion,
    PlaygroundQuestionType,
    QuestionsView,
    decisionPlaygroundLogic,
} from './decisionPlaygroundLogic'
import type { DecisionAnswerApi } from './generated/api.schemas'

export const scene: SceneExport = {
    component: DecisionPlaygroundScene,
    logic: decisionPlaygroundLogic,
}

const QUESTION_TYPE_OPTIONS: { value: PlaygroundQuestionType; label: string }[] = [
    { value: 'noul', label: 'Yes or no' },
    { value: 'choice', label: 'Multiple choice' },
    { value: 'score', label: 'Rating scale' },
]

const QUESTIONS_VIEW_OPTIONS: { value: QuestionsView; label: string }[] = [
    { value: 'form', label: 'Form' },
    { value: 'json', label: 'JSON' },
]

export function DecisionPlaygroundScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { preflight } = useValues(preflightLogic)
    const {
        state,
        questions,
        questionsView,
        questionsJson,
        questionsJsonError,
        askedQuestions,
        decision,
        decisionLoading,
        askDisabledReason,
    } = useValues(decisionPlaygroundLogic)
    const {
        setState,
        addQuestion,
        removeQuestion,
        updateQuestion,
        addOption,
        removeOption,
        updateOption,
        setQuestionsView,
        setQuestionsJson,
        askDecision,
    } = useActions(decisionPlaygroundLogic)

    // The same rule as the API: the flag enrols a project, and local development needs no flag.
    if (!featureFlags[FEATURE_FLAGS.ML_INFERENCE_DECISIONS] && !preflight?.is_debug) {
        return <NotFound object="page" />
    }

    const answerRows = decision
        ? Object.entries(decision.answers).map(([key, answer]) => {
              const question = askedQuestions.find((candidate) => candidate.key === key)
              return {
                  key,
                  question: question?.instructions ?? key,
                  scaleLabels:
                      question?.type === 'score'
                          ? question.options.map((option) => option.name.trim()).filter(Boolean)
                          : undefined,
                  answer: answer as DecisionAnswerApi,
              }
          })
        : []

    return (
        <SceneContent>
            <SceneTitleSection
                name="Decisions playground"
                description="Ask the decision model typed questions about a piece of text. Every answer is a calibrated probability, so you can see how sure the model is."
                resourceType={{ type: 'ml_inference' }}
            />
            <SceneSection title="Text to ask about">
                <LemonTextArea
                    value={state}
                    onChange={setState}
                    minRows={4}
                    placeholder="Paste a support ticket, a session summary, an error report, anything the questions are about."
                    data-attr="decision-playground-state"
                />
            </SceneSection>
            <SceneSection
                title="Questions"
                actions={
                    <LemonSegmentedButton
                        size="small"
                        value={questionsView}
                        onChange={setQuestionsView}
                        options={QUESTIONS_VIEW_OPTIONS}
                        data-attr="decision-playground-questions-view"
                    />
                }
            >
                {questionsView === 'json' ? (
                    <div className="flex flex-col gap-1">
                        <CodeEditorResizeable
                            language="json"
                            value={questionsJson}
                            onChange={(value) => setQuestionsJson(value ?? '')}
                            minHeight="8rem"
                        />
                        {questionsJsonError && <p className="text-danger text-xs m-0">{questionsJsonError}</p>}
                    </div>
                ) : (
                    <div className="flex flex-col gap-2">
                        {questions.map((question) => (
                            <QuestionRow
                                key={question.key}
                                question={question}
                                onChange={(patch) => updateQuestion(question.key, patch)}
                                onRemove={() => removeQuestion(question.key)}
                                onAddOption={() => addOption(question.key)}
                                onRemoveOption={(optionKey) => removeOption(question.key, optionKey)}
                                onChangeOption={(optionKey, patch) => updateOption(question.key, optionKey, patch)}
                            />
                        ))}
                        <div>
                            <LemonButton
                                type="secondary"
                                icon={<IconPlus />}
                                onClick={addQuestion}
                                data-attr="decision-playground-add-question"
                            >
                                Add question
                            </LemonButton>
                        </div>
                    </div>
                )}
            </SceneSection>
            <div>
                <LemonButton
                    type="primary"
                    onClick={askDecision}
                    loading={decisionLoading}
                    disabledReason={askDisabledReason}
                    data-attr="decision-playground-ask"
                >
                    Ask the model
                </LemonButton>
            </div>
            <SceneSection title="Answers">
                {decision ? (
                    <>
                        <LemonTable
                            dataSource={answerRows}
                            rowKey="key"
                            columns={[
                                { title: 'Question', dataIndex: 'question', key: 'question' },
                                {
                                    title: 'Answer',
                                    key: 'answer',
                                    render: (_, { answer, scaleLabels }) => (
                                        <DecisionAnswerCell answer={answer} scaleLabels={scaleLabels} />
                                    ),
                                },
                            ]}
                        />
                        <p className="text-secondary text-xs mt-2">
                            Answered by {decision.model} from {decision.input_tokens} input tokens
                            {decision.latency_ms !== null && decision.latency_ms !== undefined
                                ? ` in ${decision.latency_ms} ms`
                                : ''}
                            .
                        </p>
                    </>
                ) : (
                    <p className="text-secondary">No answers yet. Ask the model to see one answer per question.</p>
                )}
            </SceneSection>
        </SceneContent>
    )
}

function QuestionRow({
    question,
    onChange,
    onRemove,
    onAddOption,
    onRemoveOption,
    onChangeOption,
}: {
    question: PlaygroundQuestion
    onChange: (patch: Partial<PlaygroundQuestion>) => void
    onRemove: () => void
    onAddOption: () => void
    onRemoveOption: (optionKey: string) => void
    onChangeOption: (optionKey: string, patch: Partial<PlaygroundOption>) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2 border rounded p-3">
            <div className="flex flex-wrap gap-2 items-end">
                <div className="w-44">
                    <LemonLabel>Answer type</LemonLabel>
                    <LemonSelect
                        value={question.type}
                        onChange={(type) => type && onChange({ type })}
                        options={QUESTION_TYPE_OPTIONS}
                        fullWidth
                    />
                </div>
                <div className="flex-1 min-w-60">
                    <LemonLabel>Question</LemonLabel>
                    <LemonInput
                        value={question.instructions}
                        onChange={(instructions) => onChange({ instructions })}
                        placeholder="Is this urgent?"
                    />
                </div>
                <LemonButton
                    icon={<IconTrash />}
                    status="danger"
                    onClick={onRemove}
                    tooltip="Remove question"
                    data-attr="decision-playground-remove-question"
                />
            </div>
            {question.type !== 'noul' && (
                <div className="flex flex-col gap-1">
                    <LemonLabel>{question.type === 'choice' ? 'Options' : 'Scale, from lowest to highest'}</LemonLabel>
                    {question.options.map((option, index) => (
                        <OptionRow
                            key={option.key}
                            option={option}
                            position={question.type === 'score' ? index : undefined}
                            withMeaning={question.type === 'choice'}
                            onChange={(patch) => onChangeOption(option.key, patch)}
                            onRemove={() => onRemoveOption(option.key)}
                        />
                    ))}
                    <div>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlus />}
                            onClick={onAddOption}
                            data-attr="decision-playground-add-option"
                        >
                            {question.type === 'choice' ? 'Add option' : 'Add label'}
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}

function OptionRow({
    option,
    position,
    withMeaning,
    onChange,
    onRemove,
}: {
    option: PlaygroundOption
    /** The option's place on a rating scale, shown so the order of the labels is visible. */
    position?: number
    withMeaning: boolean
    onChange: (patch: Partial<PlaygroundOption>) => void
    onRemove: () => void
}): JSX.Element {
    return (
        <div className="flex flex-wrap gap-2 items-center">
            {position !== undefined && <span className="text-secondary w-4 text-right">{position}</span>}
            <div className="w-40">
                <LemonInput
                    value={option.name}
                    onChange={(name) => onChange({ name })}
                    placeholder={withMeaning ? 'billing' : 'calm'}
                    size="small"
                />
            </div>
            {withMeaning && (
                <div className="flex-1 min-w-60">
                    <LemonInput
                        value={option.meaning}
                        onChange={(meaning) => onChange({ meaning })}
                        placeholder="payments, invoices, refunds"
                        size="small"
                    />
                </div>
            )}
            <LemonButton
                icon={<IconTrash />}
                status="danger"
                size="small"
                onClick={onRemove}
                tooltip={withMeaning ? 'Remove option' : 'Remove label'}
                data-attr="decision-playground-remove-option"
            />
        </div>
    )
}
