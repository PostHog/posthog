import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconCheck, IconDocument } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSwitch, LemonTabs, LemonTextArea } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { dayjs } from 'lib/dayjs'
import { ColorInput } from 'scenes/surveys/wizard/ColorInput'

import { Survey, SurveyAppearance } from '~/types'

import { FeedbackPreviewMock } from './FeedbackPreviewMock'
import { getManualCaptureExample, getReactExample } from './codeExamples'
import { WizardStep, feedbackSurveyWizardLogic } from './feedbackSurveyWizardLogic'

const SURVEY_PRESET_COLORS = ['#ffffff', '#171717', '#3b82f6', '#22c55e', '#f97316', '#a855f7']

function WizardStepIndicator({ currentStep }: { currentStep: WizardStep }): JSX.Element {
    const steps: { key: WizardStep; label: string }[] = [
        { key: 'intro', label: 'Overview' },
        { key: 'configure', label: 'Configure' },
        { key: 'implement', label: 'Implement' },
    ]

    const currentIndex = steps.findIndex((s) => s.key === currentStep)

    return (
        <div className="flex items-center gap-2">
            {steps.map((step, index) => {
                const isCompleted = index < currentIndex
                const isCurrent = step.key === currentStep

                return (
                    <div key={step.key} className="flex items-center gap-2">
                        <div
                            className={`flex items-center justify-center size-6 rounded-full text-xs font-medium transition-colors ${
                                isCompleted
                                    ? 'bg-success text-white'
                                    : isCurrent
                                      ? 'bg-primary-3000 text-white'
                                      : 'bg-fill-secondary text-muted'
                            }`}
                        >
                            {isCompleted ? <IconCheck className="size-3" /> : index + 1}
                        </div>
                        <span className={`text-sm ${isCurrent ? 'font-semibold text-primary' : 'text-muted'}`}>
                            {step.label}
                        </span>
                        {index < steps.length - 1 && <div className="w-8 h-px bg-border" />}
                    </div>
                )
            })}
        </div>
    )
}

function ExistingSurveyCard({ survey, onClick }: { survey: Survey; onClick: () => void }): JSX.Element {
    const hasFollowUp = (survey.questions?.length ?? 0) > 1

    return (
        <button
            type="button"
            onClick={onClick}
            className="flex flex-col items-start gap-2 p-3 rounded-lg border border-border bg-bg-light hover:border-primary hover:bg-primary/5 transition-colors text-left cursor-pointer"
        >
            <div className="flex items-center gap-2">
                <div className="flex items-center justify-center size-8 rounded bg-fill-secondary">
                    <IconDocument className="size-4 text-muted" />
                </div>
                <span className="font-medium text-sm truncate">{survey.name}</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted">
                <span>{hasFollowUp ? 'With follow-up' : 'Thumbs only'}</span>
                <span>·</span>
                <span>{dayjs(survey.created_at).fromNow()}</span>
            </div>
        </button>
    )
}

function IntroStep({ appearance }: { appearance: SurveyAppearance }): JSX.Element {
    const { eligibleSurveys } = useValues(feedbackSurveyWizardLogic)
    const { setStep, selectExistingSurvey } = useActions(feedbackSurveyWizardLogic)
    const [thumbState, setThumbState] = useState<'none' | 'up' | 'down'>('none')

    return (
        <div className="space-y-6">
            <div>
                <h3 className="text-lg font-semibold mb-2">Collect user feedback on LLM traces</h3>
                <p className="text-muted text-sm">
                    Add thumbs up/down feedback to your AI-powered features, integrated into your own UI.
                </p>
            </div>

            <FeedbackPreviewMock
                thumbState={thumbState}
                onThumbClick={(thumb) => setThumbState(thumbState === thumb ? 'none' : thumb)}
                followUpEnabled={true}
                followUpQuestion="What went wrong?"
                surveyAppearance={appearance}
            />

            <div className="flex justify-end">
                <LemonButton type="primary" onClick={() => setStep('configure')} sideIcon={<IconArrowRight />}>
                    Create new survey
                </LemonButton>
            </div>

            {eligibleSurveys.length > 0 && (
                <div className="border-t border-border pt-4">
                    <p className="text-muted text-sm mb-3">or use an existing survey:</p>
                    <div className="grid grid-cols-3 gap-3">
                        {eligibleSurveys.map((survey) => (
                            <ExistingSurveyCard
                                key={survey.id}
                                survey={survey}
                                onClick={() => selectExistingSurvey(survey)}
                            />
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}

function ConfigureStep(): JSX.Element {
    const {
        surveyName,
        followUpEnabled,
        followUpQuestion,
        appearance,
        nameIsDuplicate,
        disabledReason,
        createdSurveyLoading,
        surveysNeedEnabling,
    } = useValues(feedbackSurveyWizardLogic)
    const { setStep, setSurveyName, setFollowUpEnabled, setFollowUpQuestion, updateAppearance, createSurvey } =
        useActions(feedbackSurveyWizardLogic)

    const [thumbState, setThumbState] = useState<'none' | 'up' | 'down'>('down')

    useEffect(() => {
        if (followUpEnabled) {
            setThumbState('down')
        }
    }, [followUpEnabled])

    return (
        <div className="space-y-6">
            <div>
                <h3 className="text-lg font-semibold mb-2">Configure your survey</h3>
                <p className="text-muted text-sm">Just the thumbs, or add a follow-up question on negative feedback.</p>
            </div>

            <div className="grid grid-cols-2 gap-6">
                <div className="space-y-4">
                    <div>
                        <label className="text-sm font-medium mb-1.5 block">Survey name</label>
                        <LemonInput
                            value={surveyName}
                            onChange={setSurveyName}
                            placeholder="LLM feedback"
                            status={nameIsDuplicate ? 'danger' : undefined}
                        />
                        {nameIsDuplicate && (
                            <p className="text-danger text-xs mt-1">A survey with this name already exists</p>
                        )}
                    </div>

                    <div className="border border-border rounded-md overflow-hidden">
                        <div className="p-3 bg-bg-light">
                            <LemonSwitch
                                checked={followUpEnabled}
                                onChange={setFollowUpEnabled}
                                label="Ask follow-up on thumbs down"
                                fullWidth
                            />
                        </div>
                        {followUpEnabled && (
                            <div className="p-3 border-t border-border space-y-4">
                                <div>
                                    <label className="text-sm font-medium mb-1.5 block">Follow-up question</label>
                                    <LemonTextArea
                                        value={followUpQuestion}
                                        onChange={setFollowUpQuestion}
                                        placeholder="What went wrong?"
                                        minRows={2}
                                    />
                                </div>

                                <div className="pt-2 border-t border-border/50 space-y-3">
                                    <label className="text-xs font-medium text-muted uppercase tracking-wide">
                                        Popup appearance
                                    </label>
                                    <div className="grid grid-cols-3 gap-3">
                                        <div className="space-y-1">
                                            <label className="text-xs font-medium">Background</label>
                                            <ColorInput
                                                value={appearance.backgroundColor}
                                                onChange={(backgroundColor) => updateAppearance({ backgroundColor })}
                                                colorList={SURVEY_PRESET_COLORS}
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <label className="text-xs font-medium">Text</label>
                                            <ColorInput
                                                value={appearance.textColor}
                                                onChange={(textColor) => updateAppearance({ textColor })}
                                                colorList={SURVEY_PRESET_COLORS}
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <label className="text-xs font-medium">Button</label>
                                            <ColorInput
                                                value={appearance.submitButtonColor}
                                                onChange={(submitButtonColor) =>
                                                    updateAppearance({ submitButtonColor })
                                                }
                                                colorList={SURVEY_PRESET_COLORS}
                                            />
                                        </div>
                                    </div>
                                    <LemonCheckbox
                                        label="Hide PostHog branding"
                                        checked={appearance.whiteLabel}
                                        onChange={(checked) => updateAppearance({ whiteLabel: checked })}
                                        size="small"
                                    />
                                </div>

                                <p className="text-muted text-xs">
                                    Need more? You'll be able to customize further after creating your survey.
                                </p>
                            </div>
                        )}
                    </div>
                </div>

                <FeedbackPreviewMock
                    thumbState={thumbState}
                    onThumbClick={(thumb) => setThumbState(thumbState === thumb ? 'none' : thumb)}
                    followUpEnabled={followUpEnabled}
                    followUpQuestion={followUpQuestion}
                    surveyAppearance={appearance}
                />
            </div>

            <div className="flex flex-col gap-2 items-end">
                <div className="flex justify-between w-full">
                    <LemonButton
                        type="secondary"
                        onClick={() => setStep('intro')}
                        icon={<IconArrowLeft />}
                        disabled={createdSurveyLoading}
                    >
                        Back
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={createSurvey}
                        sideIcon={<IconArrowRight />}
                        loading={createdSurveyLoading}
                        disabled={!!disabledReason}
                        disabledReason={disabledReason}
                    >
                        Create & continue
                    </LemonButton>
                </div>
                {surveysNeedEnabling && (
                    <p className="text-muted text-xs">This will also enable surveys for this project.</p>
                )}
            </div>
        </div>
    )
}

function ImplementStep(): JSX.Element {
    const { activeSurvey } = useValues(feedbackSurveyWizardLogic)
    const { viewSurvey } = useActions(feedbackSurveyWizardLogic)

    const [activeTab, setActiveTab] = useState<'react' | 'other'>('react')

    const followUpEnabled = (activeSurvey?.questions?.length ?? 0) > 1
    const params = { surveyId: activeSurvey?.id, followUpEnabled }
    const reactExample = getReactExample(params)
    const otherExample = getManualCaptureExample(params)

    return (
        <div className="space-y-6">
            <div>
                <h3 className="text-lg font-semibold mb-3">Implement in your app</h3>
                <div className="flex gap-2">
                    <LemonButton
                        type="primary"
                        to="https://posthog.com/docs/llm-analytics/collect-user-feedback"
                        targetBlank
                        disableClientSideRouting
                    >
                        Read the docs
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        to="https://github.com/PostHog/posthog/blob/e332d656667b8906410e93591a0f16633079efbd/frontend/src/scenes/surveys/components/question-visualizations/OpenQuestionSummaryV2.tsx#L112"
                        targetBlank
                        sideIcon={<IconArrowRight />}
                    >
                        See a real implementation in our codebase
                    </LemonButton>
                </div>
            </div>

            <LemonTabs
                activeKey={activeTab}
                onChange={setActiveTab}
                tabs={[
                    {
                        key: 'react',
                        label: 'React (useThumbSurvey)',
                        content: (
                            <div className="pt-4">
                                <CodeSnippet language={Language.JSX} wrap>
                                    {reactExample}
                                </CodeSnippet>
                            </div>
                        ),
                    },
                    {
                        key: 'other',
                        label: 'Manual capture',
                        content: (
                            <div className="pt-4">
                                <CodeSnippet language={Language.JavaScript} wrap>
                                    {otherExample}
                                </CodeSnippet>
                                <p className="text-xs text-muted mt-2">
                                    Send survey events directly.
                                    {followUpEnabled ? " You'll need to build your own follow-up UI." : ''}
                                </p>
                            </div>
                        ),
                    },
                ]}
            />

            <div className="flex justify-end">
                <LemonButton type="primary" onClick={viewSurvey}>
                    View survey
                </LemonButton>
            </div>
        </div>
    )
}

export function FeedbackSurveyWizard(): JSX.Element {
    const { step, appearance, activeSurvey } = useValues(feedbackSurveyWizardLogic)

    return (
        <div className="space-y-6">
            <WizardStepIndicator currentStep={step} />

            {step === 'intro' && <IntroStep appearance={appearance} />}
            {step === 'configure' && <ConfigureStep />}
            {step === 'implement' && activeSurvey && <ImplementStep />}
        </div>
    )
}
