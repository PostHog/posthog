import { useState } from 'react'

import { IconCheckCircle, IconClock, IconQuestion, IconTarget, IconWarning } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import type { FollowUpStage, ImpactFollowUpExample } from '../../__mocks__/impactFollowUpConceptMocks'
import { ImpactTrendChart } from './ImpactTrendChart'

type ImpactMood = 'planned' | 'promising' | 'risk' | 'no_trial' | 'missing_signal' | 'met' | 'failed' | 'unclear'

const MOOD: Record<ImpactMood, { label: string; panel: string; ink: string; stroke: string }> = {
    planned: { label: 'GOAL SET', panel: 'border-primary bg-surface-secondary', ink: 'text-primary', stroke: 'var(--brand-blue)' },
    promising: { label: 'LOOKS GOOD', panel: 'border-success bg-success-highlight', ink: 'text-success', stroke: 'var(--success)' },
    risk: { label: 'AT RISK', panel: 'border-danger bg-danger-highlight', ink: 'text-danger', stroke: 'var(--danger)' },
    no_trial: { label: 'NO TEST YET', panel: 'border-primary bg-surface-secondary', ink: 'text-primary', stroke: 'var(--border)' },
    missing_signal: { label: 'MISSING SIGNAL', panel: 'border-warning bg-warning-highlight', ink: 'text-warning', stroke: 'var(--warning)' },
    met: { label: 'WORKED', panel: 'border-success bg-success-highlight', ink: 'text-success', stroke: 'var(--success)' },
    failed: { label: "DIDN'T WORK", panel: 'border-danger bg-danger-highlight', ink: 'text-danger', stroke: 'var(--danger)' },
    unclear: { label: "CAN'T TELL", panel: 'border-warning bg-warning-highlight', ink: 'text-warning', stroke: 'var(--warning)' },
}

function reportMood(example: ImpactFollowUpExample, stage: FollowUpStage): ImpactMood {
    if (stage === 'planned') {
        return 'planned'
    }
    if (stage === 'watching') {
        return example.watchingSignal
    }
    return example.verdict === 'met' ? 'met' : example.verdict === 'failed' ? 'failed' : 'unclear'
}

function moodIcon(mood: ImpactMood): JSX.Element {
    if (mood === 'planned') {
        return <IconTarget />
    }
    if (mood === 'promising') {
        return <IconClock />
    }
    if (mood === 'met') {
        return <IconCheckCircle />
    }
    if (mood === 'risk' || mood === 'failed' || mood === 'missing_signal') {
        return <IconWarning />
    }
    return <IconQuestion />
}

export interface ImpactFollowUpConceptProps {
    example: ImpactFollowUpExample
    stage: FollowUpStage
    version: 'beacon' | 'scoreboard' | 'inbox' | 'two_signals'
}

export function ImpactFollowUpConcept({ example, stage, version }: ImpactFollowUpConceptProps): JSX.Element {
    const [trackingEnabled, setTrackingEnabled] = useState(false)
    const [actionTaken, setActionTaken] = useState(false)
    const mood = reportMood(example, stage)
    const tone = MOOD[mood]
    const days = stage === 'planned' ? 0 : stage === 'watching' ? example.elapsedDays : example.windowDays
    const sample = stage === 'planned' ? 0 : stage === 'watching' ? example.watchingSample : example.finishedSample
    const timePercent = (days / example.windowDays) * 100
    const samplePercent = Math.min((sample / example.sampleNeeded) * 100, 100)
    const currentValue = stage === 'planned' ? '—' : stage === 'watching' ? example.watchingValue : example.finishedValue
    const oneLine = stage === 'planned' ? `Before release: ${example.baseline}` : stage === 'watching' ? example.watchingNote : example.resultNote
    const isEarly = stage === 'watching'
    const stageLabel = stage === 'planned' ? 'Before release' : isEarly ? `Watching impact · ends ${example.decisionDate}` : `Final result · ended ${example.decisionDate}`

    const progress = (
        <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1 text-xs">
                <div className="flex justify-between gap-2"><span>Time</span><strong>{days} / {example.windowDays} days</strong></div>
                <LemonProgress percent={timePercent} smoothing={false} strokeColor={tone.stroke} />
            </div>
            <div className="flex flex-col gap-1 text-xs">
                <div className="flex justify-between gap-2"><span>{example.sampleLabel}</span><strong>{sample} / {example.sampleNeeded}</strong></div>
                <LemonProgress percent={samplePercent} smoothing={false} strokeColor={tone.stroke} />
            </div>
        </div>
    )

    const checks = example.evidence.map((row) => {
        const state = stage === 'planned' ? 'waiting' : isEarly ? row.watchingResult : row.result
        const checkTone = state === 'met'
            ? 'border-success bg-success-highlight text-success'
            : state === 'failed'
              ? 'border-danger bg-danger-highlight text-danger'
              : state === 'missing'
                ? 'border-warning bg-warning-highlight text-warning'
                : 'border-primary bg-surface-secondary text-secondary'
        const label = state === 'met' ? (isEarly ? 'GOOD SO FAR' : 'PASSED') : state === 'failed' ? (isEarly ? 'STILL HAPPENING' : 'FAILED') : state === 'missing' ? 'NO DATA' : 'WAITING'
        const value = stage === 'planned' ? row.baseline : isEarly ? row.watching : row.finished

        return (
            <div key={row.signal} className={`flex min-h-24 flex-col justify-between gap-2 rounded border p-3 ${checkTone}`}>
                <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-bold tracking-wider">{label}</span>
                    <span className="text-lg [&_svg]:size-5" aria-hidden="true">
                        {state === 'met' ? <IconCheckCircle /> : state === 'failed' || state === 'missing' ? <IconWarning /> : <IconClock />}
                    </span>
                </div>
                <div className="text-sm font-semibold text-primary">{row.signal}</div>
                <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-secondary">
                    <strong className="text-lg text-primary">{value}</strong><span>Goal {row.target}</span>
                </div>
            </div>
        )
    })

    const detail = (
        <div className="flex flex-col gap-3 border-t border-primary px-4 py-3 sm:px-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
                {stage === 'planned' ? (
                    <>
                        <span className="text-xs text-secondary">Check {example.window}.</span>
                        <LemonSwitch checked={trackingEnabled} onChange={setTrackingEnabled} label="Follow this impact" size="small" />
                    </>
                ) : stage === 'finished' && example.verdict !== 'met' ? (
                    <>
                        <span className="text-xs text-secondary">{example.verdict === 'failed' ? 'This result stays with the report.' : 'The window ended without a clear result.'}</span>
                        <LemonButton type="secondary" size="small" onClick={() => setActionTaken(true)}>
                            {example.verdict === 'failed' ? 'Start a new report' : 'Plan another check'}
                        </LemonButton>
                    </>
                ) : (
                    stage === 'finished' ? <span className="text-xs text-secondary">Resolved · result saved here</span> : null
                )}
            </div>
            {(trackingEnabled && stage === 'planned') || actionTaken ? (
                <div className="text-xs text-secondary">{actionTaken ? 'Draft prepared in this preview only.' : 'Following in this preview only.'}</div>
            ) : null}
            {stage === 'finished' && example.verdict !== 'met' && (
                <details>
                    <summary className="cursor-pointer text-xs text-secondary">Why this result?</summary>
                    <div className="mt-2 text-sm text-secondary">{example.reason} {example.nextStep}</div>
                </details>
            )}
            <details open={stage === 'planned' && version === 'scoreboard'}>
                <summary className="cursor-pointer text-xs text-secondary">How we check this · view query</summary>
                <div className="mt-2 flex flex-col gap-2 text-xs text-secondary">
                    <span>Starts after: {example.releaseGate}. Needs: {example.minimumEvidence}.</span>
                    <pre className="m-0 overflow-x-auto rounded border border-primary bg-surface-primary p-3 text-xs leading-relaxed"><code>{example.query}</code></pre>
                    <span>Invented values and example events. No live data.</span>
                </div>
            </details>
        </div>
    )

    if (version === 'beacon') {
        return (
            <article aria-label={`${example.title}: ${tone.label}`}>
                <LemonCard hoverEffect={false} className="overflow-hidden p-0">
                    <div className={`flex flex-wrap items-center justify-between gap-4 border-l-[10px] px-6 py-6 ${tone.panel}`}>
                        <div className="min-w-0">
                            <div className="text-xs font-medium text-secondary">{example.title} · {stageLabel}</div>
                            <h2 className={`m-0 mt-2 text-4xl font-black leading-none tracking-tight sm:text-5xl ${tone.ink}`}>{tone.label}</h2>
                            <p className="mb-0 mt-3 text-base font-semibold text-primary">{example.outcome}</p>
                        </div>
                        <div className={`shrink-0 text-[5rem] leading-none [&_svg]:size-20 ${tone.ink}`} aria-hidden="true">{moodIcon(mood)}</div>
                    </div>
                    <div className="grid items-center gap-6 px-6 py-4 md:grid-cols-[minmax(0,1fr)_minmax(13rem,1fr)]">
                        <div className="flex flex-col gap-2">
                            <div className="text-2xl font-bold">{stage === 'planned' ? example.goalShort : currentValue}</div>
                            <div className="text-sm text-secondary">{oneLine}</div>
                            {progress}
                        </div>
                        <ImpactTrendChart example={example} stage={stage} compact />
                    </div>
                    {detail}
                </LemonCard>
            </article>
        )
    }

    if (version === 'scoreboard') {
        return (
            <article aria-label={`${example.title}: ${tone.label}`}>
                <LemonCard hoverEffect={false} className="overflow-hidden p-0">
                    <div className={`flex items-center gap-3 border-l-8 px-5 py-4 ${tone.panel}`}>
                        <div className={`text-4xl [&_svg]:size-10 ${tone.ink}`} aria-hidden="true">{moodIcon(mood)}</div>
                        <div className="min-w-0">
                            <div className="text-xs text-secondary">{stageLabel}</div>
                            <div className={`text-3xl font-black leading-none ${tone.ink}`}>{tone.label}</div>
                        </div>
                    </div>
                    <div className="flex flex-col gap-3 p-4 sm:p-5">
                        <h2 className="m-0 text-base font-semibold">{example.outcome}</h2>
                        <div className="grid gap-2 sm:grid-cols-2">{checks}</div>
                        <div className="text-sm">{oneLine}</div>
                        {progress}
                    </div>
                    {detail}
                </LemonCard>
            </article>
        )
    }

    if (version === 'inbox') {
        return (
            <article aria-label={`${example.title}: ${tone.label}`}>
                <LemonCard hoverEffect={false} className="overflow-hidden p-0">
                    <div className="flex flex-col sm:flex-row">
                        <div className={`flex min-w-44 items-center gap-2 border-l-8 px-4 py-3 sm:w-48 ${tone.panel}`}>
                            <div className={`text-2xl [&_svg]:size-6 ${tone.ink}`} aria-hidden="true">{moodIcon(mood)}</div>
                            <strong className={`text-base font-black leading-tight ${tone.ink}`}>{tone.label}</strong>
                        </div>
                        <div className="flex min-w-0 flex-1 items-center justify-between gap-3 px-4 py-3">
                            <div className="min-w-0">
                                <div className="text-xs text-secondary">{example.title} · {stageLabel}</div>
                                <h2 className="m-0 mt-1 text-sm font-semibold">{example.outcome}</h2>
                                <div className="mt-1 text-xs text-secondary">{oneLine}</div>
                            </div>
                            <div className="hidden w-36 shrink-0 md:block"><ImpactTrendChart example={example} stage={stage} compact /></div>
                            <div className="shrink-0 text-right">
                                <div className="text-xl font-bold">{stage === 'planned' ? '—' : currentValue.split(' in ')[0]}</div>
                                <div className="text-xs text-secondary">{stage === 'planned' ? example.goalShort : `Day ${days}/${example.windowDays}`}</div>
                            </div>
                        </div>
                    </div>
                    {detail}
                </LemonCard>
            </article>
        )
    }

    const primarySignal = mood === 'planned' ? 'Not started' : mood === 'no_trial' || (mood === 'unclear' && example.evidence[0].result === 'missing') ? 'Nothing to measure' : mood === 'risk' || mood === 'failed' ? 'Problems remain' : 'The main number improved'
    const proofSignal = mood === 'missing_signal' || (mood === 'unclear' && example.id === 'webhook-errors')
        ? 'A signal is missing'
        : mood === 'no_trial' || (mood === 'unclear' && example.id === 'large-selection')
          ? 'No real trial yet'
          : mood === 'unclear'
            ? 'Some days have no data'
            : stage === 'finished'
              ? 'Enough to decide'
              : 'Still gathering proof'

    const primaryState = stage === 'planned' ? 'waiting' : isEarly ? example.evidence[0].watchingResult : example.evidence[0].result
    const proofState = stage === 'planned' ? 'waiting' : isEarly ? mood === 'missing_signal' ? 'missing' : 'waiting' : example.verdict === 'inconclusive' ? 'missing' : 'met'
    const primaryColor = primaryState === 'failed' ? 'border-danger bg-danger-highlight text-danger' : primaryState === 'met' ? 'border-success bg-success-highlight text-success' : 'border-primary bg-surface-secondary text-secondary'
    const proofColor = proofState === 'met' ? 'border-success bg-success-highlight text-success' : proofState === 'missing' ? 'border-warning bg-warning-highlight text-warning' : 'border-primary bg-surface-secondary text-secondary'

    return (
        <article aria-label={`${example.title}: ${tone.label}`}>
            <LemonCard hoverEffect={false} className="overflow-hidden p-0">
                <div className="px-5 py-4">
                    <div className="text-xs text-secondary">{example.title} · {stageLabel}</div>
                    <h2 className="m-0 mt-1 text-base font-semibold">{example.outcome}</h2>
                </div>
                <div className={`flex items-center justify-between gap-3 border-y px-5 py-3 ${tone.panel}`}>
                    <strong className={`text-3xl font-black ${tone.ink}`}>{tone.label}</strong>
                    <span className={`text-3xl [&_svg]:size-8 ${tone.ink}`} aria-hidden="true">{moodIcon(mood)}</span>
                </div>
                <div className="grid gap-3 p-4 sm:grid-cols-2 sm:p-5">
                    <div className={`flex items-center gap-4 rounded-lg border-2 p-4 ${primaryColor}`}>
                        <div className="flex size-16 shrink-0 items-center justify-center rounded-full border-4 border-current text-3xl [&_svg]:size-9" aria-hidden="true">
                            {primaryState === 'met' ? <IconCheckCircle /> : primaryState === 'failed' ? <IconWarning /> : <IconClock />}
                        </div>
                        <div className="min-w-0">
                            <div className="text-xs font-bold uppercase tracking-wider">1 · What changed</div>
                            <strong className="block text-lg leading-tight text-primary">{primarySignal}</strong>
                            <span className="text-xs text-secondary">{stage === 'planned' ? example.goalShort : currentValue}</span>
                        </div>
                    </div>
                    <div className={`flex items-center gap-4 rounded-lg border-2 p-4 ${proofColor}`}>
                        <div className="flex size-16 shrink-0 items-center justify-center rounded-full border-4 border-current text-3xl [&_svg]:size-9" aria-hidden="true">
                            {proofState === 'met' ? <IconCheckCircle /> : proofState === 'missing' ? <IconQuestion /> : <IconClock />}
                        </div>
                        <div className="min-w-0">
                            <div className="text-xs font-bold uppercase tracking-wider">2 · Can we tell?</div>
                            <strong className="block text-lg leading-tight text-primary">{proofSignal}</strong>
                            <span className="text-xs text-secondary">{sample} / {example.sampleNeeded} {example.sampleLabel.toLowerCase()}</span>
                        </div>
                    </div>
                </div>
                <div className="px-5 pb-4 text-sm text-secondary">{oneLine}</div>
                {detail}
            </LemonCard>
        </article>
    )
}
