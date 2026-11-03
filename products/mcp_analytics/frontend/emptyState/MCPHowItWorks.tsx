import './MCPHowItWorks.scss'

import { useActions } from 'kea'
import { type CSSProperties, type KeyboardEvent, useEffect, useRef, useState } from 'react'

import * as docBrownPng from '@posthog/brand/hoggies/png/doc-brown'
import {
    IconBrain,
    IconChat,
    IconCheck,
    IconCopy,
    IconLogomark,
    IconMCP,
    IconSparkles,
    IconTerminal,
    IconWarning,
    IconWrench,
} from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import { condenseCommand } from 'lib/components/CommandBlock/CommandBlock'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

import { ProductKey } from '~/queries/schema/schema-general'

import { useMCPAnalyticsWizardCommand } from '../onboarding/MCPAnalyticsInstall'

const HedgehogDocBrown = pngHoggie(docBrownPng)

type Step = 1 | 2 | 3
/** 0 is the frame before the first reveal, and the frame a replay restarts from. */
type Phase = 0 | Step

const STEPS: { step: Step; title: string }[] = [
    { step: 1, title: 'Wrap your MCP server' },
    { step: 2, title: 'Get a dashboard' },
    { step: 3, title: 'Ask from anywhere' },
]

const STEP_MS = 4300
// Covers the hedgehog's walk between two steps (`left` transition and three hops in the stylesheet).
const WALK_MS = 1300
const COPIED_MS = 1600

function isStatic(): boolean {
    return inStorybook() || inStorybookTestRunner() || !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

/**
 * How MCP analytics works, in three steps the Doc Brown hedgehog walks through: the setup screen's
 * sidebar. It plays 1, 2, 3 once when it scrolls into view and stops on the last step. Picking a
 * step stops the autoplay and replays that step's reveal.
 */
export function MCPHowItWorks({ mode, preview }: { mode: ProductEmptyStateMode; preview: boolean }): JSX.Element {
    const [staticRender] = useState(isStatic)
    const [phase, setPhase] = useState<Phase>(staticRender ? 3 : 0)
    const [hogAt, setHogAt] = useState<Step>(staticRender ? 3 : 1)
    const [replayTo, setReplayTo] = useState<Step | null>(null)
    const [autoplay, setAutoplay] = useState(false)
    const [walking, setWalking] = useState(false)
    const [copied, setCopied] = useState(false)
    const rootRef = useRef<HTMLDivElement>(null)
    const walkedFrom = useRef<Step>(hogAt)
    const tabRefs = useRef<(HTMLButtonElement | null)[]>([])

    const { command, isCloudOrDev } = useMCPAnalyticsWizardCommand()
    const { reportSetupInteraction } = useActions(productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }))

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
        if (phase === 3) {
            setAutoplay(false)
            return
        }
        const timeout = window.setTimeout(() => setPhase((phase + 1) as Step), STEP_MS)
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
            ArrowRight: ((selected % 3) + 1) as Step,
            ArrowLeft: (((selected + 1) % 3) + 1) as Step,
            Home: 1,
            End: 3,
        }
        const next = moves[event.key]
        if (next) {
            event.preventDefault()
            selectStep(next)
            tabRefs.current[next - 1]?.focus()
        }
    }

    const copyCommand = (): void => {
        void copyToClipboard(command, 'MCP analytics wizard command').then((ok) => {
            if (ok) {
                reportSetupInteraction('wizard command copied', mode, 'wizard', preview)
                setCopied(true)
                window.setTimeout(() => setCopied(false), COPIED_MS)
            }
        })
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
                    <div
                        className="MCPHowItWorks__step MCPHowItWorks__step--1"
                        role="tabpanel"
                        id="mcp-how-it-works-step-1"
                        aria-labelledby="mcp-how-it-works-tab-1"
                    >
                        <div className="MCPHowItWorks__stage">
                            <div className="MCPHowItWorks__ring">
                                <span className="MCPHowItWorks__ph-badge MCPHowItWorks__rv [--d:0.7s]">
                                    <IconLogomark />
                                </span>
                                <div className="MCPHowItWorks__server MCPHowItWorks__rv [--d:0.2s]">
                                    <div className="MCPHowItWorks__server-top">
                                        <IconMCP />
                                        MCP server
                                    </div>
                                    {[0, 1, 2].map((tool) => (
                                        <div key={tool} className="MCPHowItWorks__tool">
                                            <IconWrench />
                                            <i />
                                        </div>
                                    ))}
                                    <span className="MCPHowItWorks__live MCPHowItWorks__rv [--d:1.5s]">
                                        <IconCheck />
                                    </span>
                                </div>
                            </div>
                            <div className="MCPHowItWorks__wiz MCPHowItWorks__rv [--d:1s]">
                                <span className="MCPHowItWorks__wiz-prompt">$</span>
                                <span className="MCPHowItWorks__wiz-cmd">{condenseCommand(command)}</span>
                                {isCloudOrDev ? (
                                    <button
                                        type="button"
                                        className={cn('MCPHowItWorks__copy', copied && 'MCPHowItWorks__copy--done')}
                                        aria-label="Copy command"
                                        onClick={copyCommand}
                                        data-attr="mcp-analytics-how-it-works-copy-wizard"
                                    >
                                        {copied ? <IconCheck /> : <IconCopy />}
                                    </button>
                                ) : null}
                            </div>
                        </div>
                    </div>

                    <div
                        className="MCPHowItWorks__step MCPHowItWorks__step--2"
                        role="tabpanel"
                        id="mcp-how-it-works-step-2"
                        aria-labelledby="mcp-how-it-works-tab-2"
                    >
                        <div className="MCPHowItWorks__stage">
                            <div className="MCPHowItWorks__dash">
                                <div className="MCPHowItWorks__tile MCPHowItWorks__rv [--d:0.1s]">
                                    <span className="MCPHowItWorks__tile-label">
                                        <IconWrench />
                                        Tool calls
                                    </span>
                                    <span className="MCPHowItWorks__big">12.4k</span>
                                    <svg
                                        className="MCPHowItWorks__spark"
                                        viewBox="0 0 100 28"
                                        preserveAspectRatio="none"
                                    >
                                        <path
                                            className="MCPHowItWorks__draw"
                                            pathLength={1}
                                            stroke="var(--mcp-how-blue)"
                                            d="M0 22 L11 20 L22 23 L33 15 L44 17 L55 10 L66 13 L77 6 L88 8 L100 3"
                                        />
                                    </svg>
                                </div>
                                <div className="MCPHowItWorks__tile MCPHowItWorks__rv [--d:0.25s]">
                                    <span className="MCPHowItWorks__tile-label">
                                        <IconBrain />
                                        Models
                                    </span>
                                    <svg
                                        className="MCPHowItWorks__spark"
                                        viewBox="0 0 120 56"
                                        preserveAspectRatio="none"
                                    >
                                        {[14, 30, 46].map((y) => (
                                            <line
                                                key={y}
                                                className="MCPHowItWorks__grid-line"
                                                x1="0"
                                                y1={y}
                                                x2="120"
                                                y2={y}
                                            />
                                        ))}
                                        <path
                                            className="MCPHowItWorks__area"
                                            fill="var(--mcp-how-purple)"
                                            fillOpacity=".2"
                                            d="M0 44 C12 40 20 46 32 36 S52 30 62 24 S82 26 92 14 S110 10 120 6 L120 56 L0 56 Z"
                                        />
                                        <path
                                            className="MCPHowItWorks__draw"
                                            pathLength={1}
                                            stroke="var(--mcp-how-purple)"
                                            d="M0 44 C12 40 20 46 32 36 S52 30 62 24 S82 26 92 14 S110 10 120 6"
                                        />
                                        <path
                                            className="MCPHowItWorks__draw"
                                            pathLength={1}
                                            stroke="var(--mcp-how-blue)"
                                            d="M0 51 C14 48 24 50 36 45 S58 43 70 38 S96 37 106 31 S116 30 120 28"
                                        />
                                    </svg>
                                </div>
                                <div className="MCPHowItWorks__tile MCPHowItWorks__struggle MCPHowItWorks__rv [--d:0.4s]">
                                    <span className="MCPHowItWorks__tile-label">
                                        <IconWarning />
                                        Error rate
                                    </span>
                                    <ErrorRow tool="search_jobs" barClassName="[--w:7%] [--d:0.9s]" rate="4%" />
                                    <ErrorRow tool="get_listing" barClassName="[--w:16%] [--d:1s]" rate="9%" />
                                    <ErrorRow tool="book_slot" barClassName="[--w:68%] [--d:1.1s]" rate="38%" bad />
                                </div>
                            </div>
                        </div>
                    </div>

                    <div
                        className="MCPHowItWorks__step MCPHowItWorks__step--3"
                        role="tabpanel"
                        id="mcp-how-it-works-step-3"
                        aria-labelledby="mcp-how-it-works-tab-3"
                    >
                        <div className="MCPHowItWorks__stage">
                            <div className="MCPHowItWorks__chat">
                                <div className="MCPHowItWorks__sources MCPHowItWorks__rv [--d:0s]">
                                    <span className="MCPHowItWorks__source">
                                        <IconChat />
                                        Slack
                                    </span>
                                    <span className="MCPHowItWorks__source">
                                        <IconTerminal />
                                        MCP client
                                    </span>
                                    <span className="MCPHowItWorks__source">
                                        <IconSparkles />
                                        PostHog AI
                                    </span>
                                </div>
                                <div className="MCPHowItWorks__bubble MCPHowItWorks__bubble--me MCPHowItWorks__rv [--d:0.4s]">
                                    Which tools are slowest?
                                </div>
                                <div className="MCPHowItWorks__reply">
                                    <div className="MCPHowItWorks__typing">
                                        <span />
                                        <span />
                                        <span />
                                    </div>
                                    <div className="MCPHowItWorks__bubble MCPHowItWorks__bubble--ai MCPHowItWorks__rv [--d:2.4s]">
                                        <div className="MCPHowItWorks__answer">
                                            <IconSparkles />
                                            <span>Here's a ranking by p95 latency over the last 30 days.</span>
                                        </div>
                                        <div className="MCPHowItWorks__table">
                                            <div className="MCPHowItWorks__tr MCPHowItWorks__tr--head">
                                                <span>Tool</span>
                                                <span>Calls</span>
                                                <span>Errors</span>
                                                <span>p95</span>
                                            </div>
                                            <LatencyRow
                                                tool="training_runs"
                                                calls={122}
                                                errors={31}
                                                p95="287s"
                                                delayClassName="[--d:2.8s]"
                                            />
                                            <LatencyRow
                                                tool="property_defs"
                                                calls={30}
                                                errors={1}
                                                p95="80s"
                                                delayClassName="[--d:3s]"
                                            />
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="MCPHowItWorks__track" aria-hidden="true">
                    <div className="MCPHowItWorks__ground" />
                    <div className="MCPHowItWorks__fill" />
                    {STEPS.map(({ step }) => (
                        <span key={step} className={`MCPHowItWorks__dot MCPHowItWorks__dot--${step}`} />
                    ))}
                    <div className={cn('MCPHowItWorks__hog', walking && 'MCPHowItWorks__hog--walking')}>
                        <HedgehogDocBrown loading="eager" />
                    </div>
                </div>
            </section>
        </div>
    )
}

function ErrorRow({
    tool,
    barClassName,
    rate,
    bad = false,
}: {
    tool: string
    /** Sets the bar's `--w` width and `--d` reveal delay as static classes, so Tailwind can see them. */
    barClassName: string
    rate: string
    bad?: boolean
}): JSX.Element {
    return (
        <div className={cn('MCPHowItWorks__row', bad && 'MCPHowItWorks__row--bad')}>
            <b>{tool}</b>
            <span className="MCPHowItWorks__bar">
                <i className={barClassName} />
            </span>
            <span className="MCPHowItWorks__pct">
                {bad ? <IconWarning /> : null}
                {rate}
            </span>
        </div>
    )
}

function LatencyRow({
    tool,
    calls,
    errors,
    p95,
    delayClassName,
}: {
    tool: string
    calls: number
    errors: number
    p95: string
    delayClassName: string
}): JSX.Element {
    return (
        <div className={cn('MCPHowItWorks__tr MCPHowItWorks__rv', delayClassName)}>
            <b>{tool}</b>
            <span>{calls}</span>
            <span>{errors}</span>
            <span className="MCPHowItWorks__hi">{p95}</span>
        </div>
    )
}
