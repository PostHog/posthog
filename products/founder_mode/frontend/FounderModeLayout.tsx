import { useActions, useValues, BindLogic } from 'kea'
import * as React from 'react'

import { Button, cn, Spinner } from '@posthog/quill'

import { SceneExport } from 'scenes/sceneTypes'

import {
    cofounderFlowLogic,
    FounderMode,
    IDEATION_TOPICS,
    IdeationTopic,
    STEP_ORDER,
    StepKey,
} from './cofounderFlowLogic'
import { founderLandingPageLogic, LandingPageBuildSpec } from './components/founderLandingPageLogic'
import { founderValidationLogic, ValidationReport } from './components/founderValidationLogic'
import { LandingPageMockup } from './components/LandingPageMockup'
import { Step2 } from './components/Step2'
import { Step3 } from './components/Step3'
import { Step4 } from './components/Step4'
import { Step5 } from './components/Step5'
import { ValidationReportView } from './components/ValidationReportView'
import { reactionGifUrl } from './reactionGifs'
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
                <div className="p-6 max-w-3xl mx-auto">
                    <Step4 />
                </div>
            )
        case 'marketing':
            return (
                <div className="p-6 max-w-3xl mx-auto">
                    <Step5 />
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
        case 'landingLoading':
            return <LandingLoadingStep isActive={isActive} />
        case 'landingOutput':
            return <LandingOutputStep isActive={isActive} />
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

/**
 * Ideation step (step 1) — a SEQUENCE of topic-scoped mini-chats, one per big question (see
 * IDEATION_TOPICS). Topics up to and including the current one render as stacked cards; each
 * is its own back-and-forth with the cofounder. A topic auto-advances once the cofounder is
 * satisfied; the last topic doesn't — once every topic is crystallized, the founder clicks
 * "Continue to validation".
 */
function IdeaStep({ isActive }: { isActive: boolean }): JSX.Element {
    const { ideaTopicIndex, ideationComplete } = useValues(cofounderFlowLogic)
    const { proceedToValidation, startFresh } = useActions(cofounderFlowLogic)

    return (
        <div className="flex flex-col gap-5">
            <div className="flex items-center justify-between gap-3">
                <ModeToggle disabled={!isActive} />
                <button
                    type="button"
                    onClick={startFresh}
                    disabled={!isActive}
                    className="text-xs text-text-secondary hover:text-danger disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer shrink-0"
                >
                    Start fresh
                </button>
            </div>
            {IDEATION_TOPICS.map((topic, idx) => {
                if (idx > ideaTopicIndex) {
                    return null
                }
                const isCurrent = idx === ideaTopicIndex
                return (
                    <IdeaTopicChat
                        key={topic.key}
                        topic={topic}
                        index={idx}
                        isCurrent={isCurrent}
                        isActive={isActive && isCurrent}
                    />
                )
            })}
            {ideationComplete && (
                <div className="mt-1">
                    <Button variant="primary" size="sm" onClick={proceedToValidation} disabled={!isActive}>
                        Continue to validation →
                    </Button>
                </div>
            )}
        </div>
    )
}

/**
 * One big question's mini-chat within ideation. Past topics render muted and read-only with
 * a crystallized summary; the current topic renders the live chat (thread + input).
 */
function IdeaTopicChat({
    topic,
    index,
    isCurrent,
    isActive,
}: {
    topic: IdeationTopic
    index: number
    isCurrent: boolean
    isActive: boolean
}): JSX.Element {
    const { draft, ideaSubmitting, ideaError, ideaMessages, crystallizedByTopic } = useValues(cofounderFlowLogic)
    const { setDraft, sendIdeaAnswer, resetIdeaChat } = useActions(cofounderFlowLogic)
    const ref = React.useRef<HTMLTextAreaElement>(null)
    const cardRef = React.useRef<HTMLDivElement>(null)
    React.useEffect(() => {
        if (isActive) {
            ref.current?.focus()
        }
    }, [isActive])
    React.useEffect(() => {
        if (isCurrent) {
            cardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
    }, [isCurrent])

    const messages = ideaMessages[topic.key] ?? []
    const hasThread = messages.length > 0
    const crystallized = crystallizedByTopic[topic.key]
    const isDone = !!crystallized
    const canSend = isActive && !!draft.trim() && !ideaSubmitting

    return (
        <div
            ref={cardRef}
            className={cn(
                'rounded-lg border p-4 transition-opacity',
                isDone && !isCurrent ? 'border-border bg-bg-3000/40 opacity-80' : 'border-border-bold/40 bg-white'
            )}
        >
            <div className="flex items-baseline justify-between gap-3 mb-3">
                <h3 className="text-lg font-semibold flex items-baseline gap-2">
                    <span className="text-text-tertiary text-sm tabular-nums">
                        {index + 1}/{IDEATION_TOPICS.length}
                    </span>
                    {topic.heading}
                    {isDone && <span className="text-success text-sm">✓</span>}
                </h3>
                {hasThread && isCurrent && (
                    <button
                        type="button"
                        onClick={() => resetIdeaChat(topic.key)}
                        disabled={ideaSubmitting}
                        className="text-xs text-text-secondary hover:text-text-primary disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer shrink-0"
                    >
                        ↻ Start over
                    </button>
                )}
            </div>

            {hasThread && (
                <div className="flex flex-col gap-3 mb-4">
                    {messages.map((m, i) => {
                        const gif = m.author === 'agent' ? reactionGifUrl(m.reactionKey) : null
                        return (
                            <div
                                key={i}
                                className={cn(
                                    'flex flex-col gap-1 max-w-[90%]',
                                    m.author === 'agent' ? 'self-start' : 'self-end'
                                )}
                            >
                                {gif && (
                                    <img
                                        src={gif}
                                        alt={m.reactionKey ?? 'reaction'}
                                        className="rounded-md max-h-40 max-w-[16rem] w-auto h-auto border border-border-bold/30"
                                    />
                                )}
                                <div
                                    className={cn(
                                        'text-sm rounded-md px-3 py-2 whitespace-pre-wrap',
                                        m.author === 'agent'
                                            ? 'bg-bg-3000 text-text-primary'
                                            : 'bg-text-primary text-bg-primary'
                                    )}
                                >
                                    {m.value}
                                </div>
                            </div>
                        )
                    })}
                    {isCurrent && ideaSubmitting && (
                        <div className="text-sm text-text-secondary self-start px-3 py-2">JT is thinking…</div>
                    )}
                </div>
            )}

            {isDone ? (
                <IdeaTopicSummary topic={topic} crystallized={crystallized} />
            ) : isCurrent ? (
                <>
                    <textarea
                        ref={ref}
                        className="w-full border border-border-bold/40 rounded-md p-3 text-sm bg-white focus:outline-none focus:border-text-primary min-h-[120px] resize-none disabled:opacity-60 disabled:bg-bg-3000"
                        placeholder={hasThread ? 'Answer JT…' : topic.placeholder}
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                                e.preventDefault()
                                if (canSend) {
                                    sendIdeaAnswer(topic.key, draft)
                                }
                            }
                        }}
                        disabled={!isActive || ideaSubmitting}
                    />
                    {ideaError && <p className="text-danger text-sm mt-2">{ideaError}</p>}
                    <div className="mt-3">
                        <Button
                            variant="primary"
                            size="sm"
                            onClick={() => sendIdeaAnswer(topic.key, draft)}
                            disabled={!canSend}
                        >
                            {ideaSubmitting ? 'Sending…' : hasThread ? 'Send' : 'Send it'}
                        </Button>
                    </div>
                </>
            ) : null}
        </div>
    )
}

// Recap of what the cofounder crystallized for a finished ideation topic. Read-only by
// default; the founder can flip it into edit mode to tweak the synthesized prose in place.
function IdeaTopicSummary({
    topic,
    crystallized,
}: {
    topic: IdeationTopic
    crystallized: Record<string, string>
}): JSX.Element {
    const { editingTopics } = useValues(cofounderFlowLogic)
    const { toggleTopicEditing, setCrystallizedField } = useActions(cofounderFlowLogic)
    const isEditing = !!editingTopics[topic.key]

    return (
        <div className="flex flex-col gap-2 rounded-md bg-bg-3000/60 p-3">
            <div className="flex justify-end -mt-1 -mr-1">
                <button
                    type="button"
                    onClick={() => toggleTopicEditing(topic.key)}
                    className="text-xs text-text-secondary hover:text-text-primary cursor-pointer"
                >
                    {isEditing ? 'Done' : '✎ Edit'}
                </button>
            </div>
            {Object.entries(crystallized).map(([key, val]) => (
                <div key={key}>
                    <div className="text-xs uppercase tracking-wide text-text-tertiary">{key.replace(/_/g, ' ')}</div>
                    {isEditing ? (
                        <textarea
                            className="w-full border border-border-bold/40 rounded-md p-2 text-sm bg-white focus:outline-none focus:border-text-primary min-h-[72px] resize-none"
                            value={val}
                            onChange={(e) => setCrystallizedField(topic.key, key, e.target.value)}
                        />
                    ) : (
                        <div className="text-sm text-text-primary whitespace-pre-wrap">{val}</div>
                    )}
                </div>
            ))}
        </div>
    )
}

// Small inline switcher for which half of the founding team the cofounder plays. Mode is
// rolled 50/50 on mount; this lets the founder flip it if the draw doesn't fit them.
// Switching keeps the conversation — the next /cofounder_turn/ runs with the new mode.
function ModeToggle({ disabled }: { disabled: boolean }): JSX.Element {
    const { founderMode } = useValues(cofounderFlowLogic)
    const { setFounderMode } = useActions(cofounderFlowLogic)
    const options: { mode: FounderMode; label: string }[] = [
        { mode: 'technical_cofounder', label: 'Technical' },
        { mode: 'commercial_cofounder', label: 'Commercial' },
    ]
    return (
        <div className="mb-4 flex items-center gap-2 text-xs text-text-secondary">
            <span>Your cofounder:</span>
            <div className="inline-flex rounded-full border border-border-bold/40 bg-bg-3000 p-0.5">
                {options.map(({ mode, label }) => {
                    const isSelected = founderMode === mode
                    return (
                        <button
                            key={mode}
                            type="button"
                            disabled={disabled}
                            onClick={() => setFounderMode(mode)}
                            className={cn(
                                'px-3 py-1 rounded-full transition-all',
                                disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
                                isSelected
                                    ? 'bg-text-primary text-bg-primary font-semibold shadow-sm'
                                    : 'text-text-tertiary hover:text-text-primary'
                            )}
                        >
                            {label}
                        </button>
                    )
                })}
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

function LandingLoadingStep({ isActive }: { isActive: boolean }): JSX.Element {
    const { projectId } = useValues(cofounderFlowLogic)
    const { advance } = useActions(cofounderFlowLogic)

    if (!projectId) {
        return (
            <LoadingBlock
                title="Drafting your landing page"
                body="One sec while I queue up the landing-page build spec."
            />
        )
    }

    return (
        <BindLogic logic={founderLandingPageLogic} props={{ projectId }}>
            <LandingLoadingInner isActive={isActive} onReady={advance} />
        </BindLogic>
    )
}

function LandingLoadingInner({ isActive, onReady }: { isActive: boolean; onReady: () => void }): JSX.Element {
    const { spec, status } = useValues(founderLandingPageLogic)
    const { generate } = useActions(founderLandingPageLogic)
    const triggeredRef = React.useRef(false)
    const readyRef = React.useRef(false)

    // Kick off generation once when this step becomes active and nothing has been
    // produced yet. Subsequent visits to this step rely on the polled status.
    React.useEffect(() => {
        if (isActive && !triggeredRef.current && !spec && (status == null || status === 'failed')) {
            triggeredRef.current = true
            generate()
        }
    }, [isActive, spec, status, generate])

    React.useEffect(() => {
        if (isActive && !readyRef.current && status === 'completed' && spec) {
            readyRef.current = true
            onReady()
        }
    }, [isActive, status, spec, onReady])

    return (
        <LoadingBlock
            title="Drafting your landing page"
            body={
                status === 'failed'
                    ? "That didn't generate cleanly. Try again from the landing-page step."
                    : 'Pulling in your idea, validation, and GTM answers to draft the landing-page build spec.'
            }
        />
    )
}

function LandingOutputStep({ isActive }: { isActive: boolean }): JSX.Element {
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
        <BindLogic logic={founderLandingPageLogic} props={{ projectId }}>
            <LandingOutputInner isActive={isActive} onNext={advance} />
        </BindLogic>
    )
}

function LandingOutputInner({ isActive, onNext }: { isActive: boolean; onNext: () => void }): JSX.Element {
    const { spec } = useValues(founderLandingPageLogic) as { spec: LandingPageBuildSpec | null }
    return (
        <div>
            <h2 className="text-2xl font-semibold mb-4">Here's your landing page draft</h2>
            {spec ? <LandingPageMockup spec={spec} /> : <LoadingBlock title="Loading landing-page spec…" body="" />}
            <div className="mt-6">
                <Button variant="primary" size="sm" onClick={onNext} disabled={!isActive || !spec}>
                    Next
                </Button>
            </div>
        </div>
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
