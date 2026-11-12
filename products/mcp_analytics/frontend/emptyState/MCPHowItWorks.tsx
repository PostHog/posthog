import './MCPHowItWorks.scss'

import { type CSSProperties, type ComponentType, type KeyboardEvent, useEffect, useRef, useState } from 'react'

import * as docBrownPng from '@posthog/brand/hoggies/png/doc-brown'

import { pngHoggie } from 'lib/brand/hoggies'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { cn } from 'lib/utils/css-classes'
import { inStorybook } from 'lib/utils/dom'

import { MCPHowItWorksAskStage } from './MCPHowItWorksAskStage'
import { MCPHowItWorksDashboardStage } from './MCPHowItWorksDashboardStage'
import { MCPHowItWorksWrapStage } from './MCPHowItWorksWrapStage'

const HedgehogDocBrown = pngHoggie(docBrownPng)

type Step = number
/** 0 is the frame before the first reveal, and the frame a replay restarts from. */
type Phase = 0 | Step

interface MCPHowItWorksProps {
    mode: ProductEmptyStateMode
    preview: boolean
}

const STEPS: { step: Step; title: string; Stage: ComponentType<MCPHowItWorksProps> }[] = [
    { step: 1, title: 'Wrap your MCP server', Stage: MCPHowItWorksWrapStage },
    { step: 2, title: 'Get a dashboard', Stage: MCPHowItWorksDashboardStage },
    { step: 3, title: 'Ask from anywhere', Stage: MCPHowItWorksAskStage },
]
const LAST_STEP: Step = STEPS.length

const STEP_MS = 4300
// Covers the hedgehog's walk between two steps (`transform` transition and three hops in the stylesheet).
const WALK_MS = 1300

function isStatic(): boolean {
    return inStorybook() || !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

/**
 * How MCP analytics works, in three steps the Doc Brown hedgehog walks through: the setup screen's
 * sidebar. It plays 1, 2, 3 once when it scrolls into view and stops on the last step. Picking a
 * step stops the autoplay and replays that step's reveal.
 */
export function MCPHowItWorks({ mode, preview }: MCPHowItWorksProps): JSX.Element {
    const [staticRender] = useState(isStatic)
    const [phase, setPhase] = useState<Phase>(staticRender ? LAST_STEP : 0)
    const [hogAt, setHogAt] = useState<Step>(staticRender ? LAST_STEP : 1)
    const [replayTo, setReplayTo] = useState<Step | null>(null)
    const [autoplay, setAutoplay] = useState(false)
    const [walking, setWalking] = useState(false)
    const rootRef = useRef<HTMLDivElement>(null)
    const walkedFrom = useRef<Step>(hogAt)
    const tabRefs = useRef<(HTMLButtonElement | null)[]>([])

    useEffect(() => {
        const root = rootRef.current
        if (staticRender || !root) {
            return
        }
        const observer = new IntersectionObserver(
            ([entry]) => {
                if (entry.isIntersecting) {
                    observer.disconnect()
                    setPhase(1)
                    setAutoplay(true)
                }
            },
            { threshold: 0.3 }
        )
        observer.observe(root)
        return () => observer.disconnect()
    }, [staticRender])

    useEffect(() => {
        if (!autoplay || phase === 0) {
            return
        }
        if (phase === LAST_STEP) {
            setAutoplay(false)
            return
        }
        const timeout = window.setTimeout(() => setPhase(phase + 1), STEP_MS)
        return () => window.clearTimeout(timeout)
    }, [autoplay, phase])

    useEffect(() => {
        if (phase !== 0) {
            setHogAt(phase)
        }
    }, [phase])

    useEffect(() => {
        if (staticRender || walkedFrom.current === hogAt) {
            return
        }
        walkedFrom.current = hogAt
        setWalking(true)
        const timeout = window.setTimeout(() => setWalking(false), WALK_MS)
        return () => window.clearTimeout(timeout)
    }, [hogAt, staticRender])

    // A replay holds phase 0 for two frames, so the browser paints the hidden state before the reveal transitions run.
    useEffect(() => {
        if (replayTo === null) {
            return
        }
        let second = 0
        const first = window.requestAnimationFrame(() => {
            second = window.requestAnimationFrame(() => {
                setPhase(replayTo)
                setReplayTo(null)
            })
        })
        return () => {
            window.cancelAnimationFrame(first)
            window.cancelAnimationFrame(second)
        }
    }, [replayTo])

    const selected: Step = replayTo ?? (phase === 0 ? 1 : phase)

    const selectStep = (step: Step): void => {
        setAutoplay(false)
        if (staticRender) {
            setPhase(step)
            return
        }
        setPhase(0)
        setReplayTo(step)
    }

    const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>): void => {
        const moves: Record<string, Step> = {
            ArrowRight: (selected % LAST_STEP) + 1,
            ArrowLeft: ((selected + LAST_STEP - 2) % LAST_STEP) + 1,
            Home: 1,
            End: LAST_STEP,
        }
        const next = moves[event.key]
        if (next) {
            event.preventDefault()
            selectStep(next)
            tabRefs.current[next - 1]?.focus()
        }
    }

    return (
        <div className={cn('MCPHowItWorks', staticRender && 'MCPHowItWorks--static')} ref={rootRef}>
            <section
                className={cn(
                    'MCPHowItWorks__diagram',
                    autoplay && 'MCPHowItWorks__diagram--auto',
                    !autoplay && phase !== 0 && 'MCPHowItWorks__diagram--done'
                )}
                data-phase={phase}
                data-hog={hogAt}
                style={{ '--mcp-how-step-duration': `${STEP_MS}ms` } as CSSProperties}
                aria-label="MCP analytics in three steps: wrap your MCP server, get a pre-built dashboard, ask questions from anywhere"
            >
                <div className="MCPHowItWorks__tabs" role="tablist" aria-label="How MCP analytics works, step by step">
                    {STEPS.map(({ step, title }) => (
                        <button
                            key={step}
                            ref={(element) => {
                                tabRefs.current[step - 1] = element
                            }}
                            type="button"
                            role="tab"
                            id={`mcp-how-it-works-tab-${step}`}
                            aria-controls={`mcp-how-it-works-step-${step}`}
                            aria-selected={selected === step}
                            tabIndex={selected === step ? 0 : -1}
                            className="MCPHowItWorks__tab"
                            data-p={step}
                            onClick={() => selectStep(step)}
                            onKeyDown={onTabKeyDown}
                            data-attr={`mcp-analytics-how-it-works-step-${step}`}
                        >
                            <span className="MCPHowItWorks__tab-num">{step}</span>
                            <span className="MCPHowItWorks__tab-title">{title}</span>
                        </button>
                    ))}
                </div>

                <div className="MCPHowItWorks__flow">
                    {STEPS.map(({ step, Stage }) => (
                        <div
                            key={step}
                            className={`MCPHowItWorks__step MCPHowItWorks__step--${step}`}
                            role="tabpanel"
                            id={`mcp-how-it-works-step-${step}`}
                            aria-labelledby={`mcp-how-it-works-tab-${step}`}
                        >
                            <div className="MCPHowItWorks__stage">
                                <Stage mode={mode} preview={preview} />
                            </div>
                        </div>
                    ))}
                </div>

                <div className="MCPHowItWorks__track" aria-hidden="true">
                    <div className="MCPHowItWorks__ground" />
                    <div className="MCPHowItWorks__fill" />
                    {STEPS.map(({ step }) => (
                        <span key={step} className={`MCPHowItWorks__dot MCPHowItWorks__dot--${step}`} />
                    ))}
                    <div className={cn('MCPHowItWorks__hog', walking && 'MCPHowItWorks__hog--walking')}>
                        <div className="MCPHowItWorks__hog-body">
                            <HedgehogDocBrown loading="eager" />
                        </div>
                    </div>
                </div>
            </section>
        </div>
    )
}
