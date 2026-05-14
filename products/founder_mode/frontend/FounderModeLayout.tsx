import { useActions, useValues, BindLogic } from 'kea'
import * as React from 'react'

import { Button, cn, Spinner } from '@posthog/quill'

import { SceneExport } from 'scenes/sceneTypes'

import { cofounderFlowLogic, STEP_ORDER, StepKey } from './cofounderFlowLogic'
import { founderValidationLogic, ValidationReport } from './components/founderValidationLogic'
import { Step2 } from './components/Step2'
import { Step3 } from './components/Step3'
import { Step4 } from './components/Step4'
import { ValidationReportView } from './components/ValidationReportView'
import { founderLogic, FounderStep, FOUNDER_STEPS } from './scenes/founderLogic'

const FADE_MASK_HEIGHT = 160

const STEP_LABELS: Record<FounderStep, string> = {
    ideation: 'Ideation',
    validation: 'Validation',
    gtm: 'Go-to-market',
    mvp: 'MVP',
    marketing: 'Marketing',
}

function StepNav(): JSX.Element {
    const { currentStep } = useValues(founderLogic)
    const { advanceStep } = useActions(founderLogic)
    const currentIdx = FOUNDER_STEPS.indexOf(currentStep)

    return (
        <nav className="flex items-center gap-1 px-4 py-2 border-b border-border bg-white/80 backdrop-blur-sm">
            {FOUNDER_STEPS.map((step, idx) => {
                const isActive = step === currentStep
                const isPast = idx < currentIdx
                return (
                    <React.Fragment key={step}>
                        {idx > 0 && <span className="text-border mx-1 select-none">›</span>}
                        <button
                            type="button"
                            onClick={() => isPast && advanceStep(step)}
                            className={cn(
                                'px-2.5 py-1 rounded text-xs font-medium transition-colors',
                                isActive && 'bg-primary/10 text-primary',
                                isPast && 'text-text-secondary hover:text-text-primary cursor-pointer',
                                !isActive && !isPast && 'text-text-secondary/50 cursor-default'
                            )}
                            disabled={!isPast}
                        >
                            {STEP_LABELS[step]}
                        </button>
                    </React.Fragment>
                )
            })}
        </nav>
    )
}

function StepContent({ step }: { step: FounderStep }): JSX.Element {
    switch (step) {
        case 'validation':
            return (
                <div className="p-6 max-w-3xl mx-auto">
                    <Step2 />
                </div>
            )
        case 'gtm':
            return (
                <div className="p-6 max-w-3xl mx-auto">
                    <Step3 />
                </div>
            )
        case 'mvp':
            return (
                <div className="p-6 max-w-3xl mx-auto flex flex-col items-center justify-center gap-4 text-center min-h-[50vh]">
                    <h2 className="text-2xl font-semibold">MVP</h2>
                    <p className="text-text-secondary max-w-md">
                        The MVP spec stage is coming soon. For now, continue to marketing.
                    </p>
                    <Button variant="primary" size="sm" onClick={() => founderLogic.actions.advanceStep('marketing')}>
                        Continue to marketing →
                    </Button>
                </div>
            )
        case 'marketing':
            return (
                <div className="p-6 max-w-3xl mx-auto">
                    <Step4 />
                </div>
            )
        default:
            return <></>
    }
}

export function FounderModeLayout(): JSX.Element {
    const { currentStep, hasExistingProject, projectLoaded } = useValues(founderLogic)

    // If there's an existing project past ideation, skip the cofounder flow and go
    // straight to the persisted step's UI.
    const resumingPastIdeation = hasExistingProject && currentStep !== 'ideation'

    if (!projectLoaded) {
        return (
            <main className="fixed inset-0 top-[54px] flex items-center justify-center bg-white">
                <Spinner />
            </main>
        )
    }

    if (resumingPastIdeation) {
        return (
            <main
                className="fixed inset-0 top-[54px] flex flex-col bg-white overflow-hidden"
                style={{
                    backgroundColor: '#fff',
                    backgroundSize: '13px 13px',
                    backgroundImage: 'radial-gradient(1px, var(--color-gray-300), var(--color-gray-50))',
                }}
            >
                <StepNav />
                <section className="flex-1 relative overflow-y-auto">
                    <StepContent step={currentStep} />
                </section>
            </main>
        )
    }

    return (
        <main
            className="fixed inset-0 top-[54px] flex flex-col bg-white overflow-hidden"
            style={{
                backgroundColor: '#fff',
                backgroundSize: '13px 13px',
                backgroundImage: 'radial-gradient(1px, var(--color-gray-300), var(--color-gray-50))',
            }}
        >
            <DebugMenu />
            <FlowTimeline />
        </main>
    )
}

function DebugMenu(): JSX.Element {
    const { currentStepKey } = useValues(cofounderFlowLogic)
    const { goToStep } = useActions(cofounderFlowLogic)
    return (
        <div className="absolute top-2 right-3 z-50 flex items-center gap-2 text-[10px] uppercase tracking-wide text-text-secondary">
            <span className="px-1.5 py-0.5 rounded bg-bg-3000 border border-border">{currentStepKey}</span>
            <select
                className="text-[10px] px-1 py-0.5 rounded border border-border bg-white"
                value={currentStepKey}
                onChange={(e) => goToStep(e.target.value as StepKey)}
            >
                {STEP_ORDER.map((key) => (
                    <option key={key} value={key}>
                        {key}
                    </option>
                ))}
            </select>
        </div>
    )
}

/**
 * Vertical scrolling timeline. Each step is rendered as a block stacked top-to-bottom.
 * On step advance we scroll the active block to a fixed offset from the top of the
 * viewport and fade older blocks behind a top mask, so the whole flow feels like one
 * continuous scrolling thought.
 */
function FlowTimeline(): JSX.Element {
    const { stepIndex, currentStepKey } = useValues(cofounderFlowLogic)
    const scrollRef = React.useRef<HTMLDivElement>(null)
    const stepRefs = React.useRef<Record<StepKey, HTMLDivElement | null>>({} as never)

    // Smoothly scroll the active step to the top of the viewport (with offset for mask).
    React.useEffect(() => {
        const target = stepRefs.current[currentStepKey]
        const container = scrollRef.current
        if (!target || !container) {
            return
        }
        const offset = target.offsetTop - FADE_MASK_HEIGHT
        container.scrollTo({ top: offset, behavior: 'smooth' })
    }, [currentStepKey])

    return (
        <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto px-6 pb-[60vh]"
            style={{
                paddingTop: FADE_MASK_HEIGHT + 80,
                maskImage: `linear-gradient(to bottom, transparent 0px, black ${FADE_MASK_HEIGHT}px)`,
                WebkitMaskImage: `linear-gradient(to bottom, transparent 0px, black ${FADE_MASK_HEIGHT}px)`,
            }}
        >
            <div className="max-w-xl mx-auto flex flex-col gap-24">
                {STEP_ORDER.map((key, idx) => (
                    <div
                        key={key}
                        ref={(el) => {
                            stepRefs.current[key] = el
                        }}
                        className={cn(
                            'transition-opacity duration-500',
                            idx < stepIndex
                                ? 'opacity-30'
                                : idx === stepIndex
                                  ? 'opacity-100'
                                  : 'opacity-0 pointer-events-none'
                        )}
                    >
                        <StepBlock stepKey={key} isActive={idx === stepIndex} />
                    </div>
                ))}
            </div>
        </div>
    )
}

function StepBlock({ stepKey, isActive }: { stepKey: StepKey; isActive: boolean }): JSX.Element {
    switch (stepKey) {
        case 'intro':
            return <IntroStep isActive={isActive} />
        case 'idea':
            return <IdeaStep isActive={isActive} />
        case 'validationLoading':
            return <ValidationLoadingStep isActive={isActive} />
        case 'validationOutput':
            return <ValidationOutputStep isActive={isActive} />
        case 'gtmLoading':
            return <GTMLoadingStep />
        case 'gtmItem':
            return (
                <PromptStep
                    stepKey="gtmItem"
                    title="Tell me about what you're making"
                    placeholder="One sentence is fine"
                />
            )
        case 'gtmPositioning':
            return (
                <PromptStep
                    stepKey="gtmPositioning"
                    title="How would you position it against alternatives?"
                    placeholder="What angle wins?"
                />
            )
        case 'happyPath':
            return (
                <PromptStep
                    stepKey="happyPath"
                    title="Walk me through the happy path"
                    placeholder="First click → first 'wow' moment"
                />
            )
        case 'marketing':
            return (
                <PromptStep
                    stepKey="marketing"
                    title="How will you get your first 100 users?"
                    placeholder="Channels, communities, the cheap stuff first"
                />
            )
        case 'done':
            return <DoneStep />
    }
}

function IntroStep({ isActive }: { isActive: boolean }): JSX.Element {
    const { advance } = useActions(cofounderFlowLogic)
    return (
        <div>
            <h2 className="text-2xl font-semibold mb-3">I'm your personal cofounder</h2>
            <p className="text-text-primary leading-relaxed">
                I'm here to listen to your idea, work through it, validate it, and if it's a good idea, you'll be an
                indie hacker rockstar.
            </p>
            <p className="text-text-primary leading-relaxed mt-3">
                I want to see you flourish, so try and work with me and answer as many questions as possible.
            </p>
            <div className="flex gap-3 mt-6">
                <Button variant="primary" size="sm" onClick={advance} disabled={!isActive}>
                    I'm ready
                </Button>
                <Button variant="outline" size="sm" disabled={!isActive}>
                    Tell me more first
                </Button>
            </div>
        </div>
    )
}

function IdeaStep({ isActive }: { isActive: boolean }): JSX.Element {
    const { draft, ideaSubmitting, ideaError } = useValues(cofounderFlowLogic)
    const { setDraft, submitIdea } = useActions(cofounderFlowLogic)
    const ref = React.useRef<HTMLTextAreaElement>(null)
    React.useEffect(() => {
        if (isActive) {
            ref.current?.focus()
        }
    }, [isActive])
    return (
        <div>
            <h2 className="text-2xl font-semibold mb-3">So what's your idea?</h2>
            <textarea
                ref={ref}
                className="w-full border border-border-bold/40 rounded-md p-3 text-sm bg-white focus:outline-none focus:border-text-primary min-h-[140px] resize-none disabled:opacity-60 disabled:bg-bg-3000"
                placeholder="Pitch me in a few sentences."
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                        e.preventDefault()
                        submitIdea()
                    }
                }}
                disabled={!isActive || ideaSubmitting}
            />
            {ideaError && <p className="text-danger text-sm mt-2">{ideaError}</p>}
            <div className="mt-4">
                <Button
                    variant="primary"
                    size="sm"
                    onClick={submitIdea}
                    disabled={!isActive || !draft.trim() || ideaSubmitting}
                >
                    {ideaSubmitting ? 'Sending…' : 'Send it'}
                </Button>
            </div>
        </div>
    )
}

function ValidationLoadingStep({ isActive }: { isActive: boolean }): JSX.Element {
    const { projectId } = useValues(cofounderFlowLogic)
    const { advance } = useActions(cofounderFlowLogic)

    if (!projectId) {
        return <LoadingBlock title="Right so let's summarize" body="One sec while I gather your idea." />
    }

    return (
        <BindLogic logic={founderValidationLogic} props={{ projectId }}>
            <ValidationLoadingInner isActive={isActive} onReady={advance} />
        </BindLogic>
    )
}

function ValidationLoadingInner({ isActive, onReady }: { isActive: boolean; onReady: () => void }): JSX.Element {
    const { report, status } = useValues(founderValidationLogic)
    const readyRef = React.useRef(false)

    React.useEffect(() => {
        if (isActive && !readyRef.current && status === 'completed' && report) {
            readyRef.current = true
            onReady()
        }
    }, [isActive, status, report, onReady])

    return (
        <LoadingBlock
            title="Right so let's summarize"
            body={
                status === 'failed'
                    ? "Hmm, that didn't land. Let me know if you want to retry."
                    : "Let me just look around and see if this idea is objectively good. My intuition doesn't really say much to me right now."
            }
        />
    )
}

function ValidationOutputStep({ isActive }: { isActive: boolean }): JSX.Element {
    const { projectId } = useValues(cofounderFlowLogic)
    const { advance } = useActions(cofounderFlowLogic)

    if (!projectId) {
        return (
            <div>
                <p className="text-text-secondary">No project found.</p>
            </div>
        )
    }
    return (
        <BindLogic logic={founderValidationLogic} props={{ projectId }}>
            <ValidationOutputInner isActive={isActive} onNext={advance} />
        </BindLogic>
    )
}

function ValidationOutputInner({ isActive, onNext }: { isActive: boolean; onNext: () => void }): JSX.Element {
    const { report } = useValues(founderValidationLogic) as { report: ValidationReport | null }
    return (
        <div>
            {report ? <ValidationReportView report={report} /> : <LoadingBlock title="Loading report…" body="" />}
            <div className="mt-6">
                <Button variant="primary" size="sm" onClick={onNext} disabled={!isActive || !report}>
                    Next
                </Button>
            </div>
        </div>
    )
}

function GTMLoadingStep(): JSX.Element {
    return (
        <LoadingBlock
            title="Nice, let's move on to Go to market"
            body="Positioning is the difference between a product people get and one they shrug at. Let's nail it."
        />
    )
}

function PromptStep({
    stepKey,
    title,
    placeholder,
}: {
    stepKey: keyof import('./cofounderFlowLogic').CofounderAnswers
    title: string
    placeholder: string
}): JSX.Element {
    const { draft, answers, currentStepKey } = useValues(cofounderFlowLogic)
    const { setDraft, setAnswer, advance } = useActions(cofounderFlowLogic)
    const isActive = currentStepKey === stepKey
    const ref = React.useRef<HTMLTextAreaElement>(null)
    React.useEffect(() => {
        if (isActive) {
            ref.current?.focus()
        }
    }, [isActive])
    const submit = (): void => {
        const value = draft.trim()
        if (!value) {
            return
        }
        setAnswer(stepKey, value)
        advance()
    }
    const value = isActive ? draft : answers[stepKey]
    return (
        <div>
            <h2 className="text-2xl font-semibold mb-3">{title}</h2>
            <textarea
                ref={ref}
                className="w-full border border-border-bold/40 rounded-md p-3 text-sm bg-white focus:outline-none focus:border-text-primary min-h-[120px] resize-none disabled:opacity-60 disabled:bg-bg-3000"
                placeholder={placeholder}
                value={value}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                        e.preventDefault()
                        submit()
                    }
                }}
                disabled={!isActive}
            />
            <div className="mt-4">
                <Button variant="primary" size="sm" onClick={submit} disabled={!isActive || !draft.trim()}>
                    Send it
                </Button>
            </div>
        </div>
    )
}

function DoneStep(): JSX.Element {
    return (
        <div>
            <h2 className="text-2xl font-semibold mb-3">Alright, you've got the bones.</h2>
            <p className="text-text-primary leading-relaxed">
                Idea, validation, positioning, happy path, marketing. Go build the smallest version and put it in front
                of someone today.
            </p>
        </div>
    )
}

function LoadingBlock({ title, body }: { title: string; body: string }): JSX.Element {
    return (
        <div>
            <h2 className="text-2xl font-semibold mb-2">{title}</h2>
            {body && <p className="text-text-primary leading-relaxed">{body}</p>}
            <div className="mt-6">
                <Spinner className="w-8 h-8 text-text-primary" />
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: FounderModeLayout,
    logic: founderLogic,
}
