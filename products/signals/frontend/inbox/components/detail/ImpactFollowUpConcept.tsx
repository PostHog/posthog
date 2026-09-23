import { useState } from 'react'

import { IconCheckCircle, IconClock, IconQuestion, IconWarning } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import type { FollowUpStage, ImpactFollowUpExample } from '../../__mocks__/impactFollowUpConceptMocks'
import { ImpactTrendChart } from './ImpactTrendChart'

type Reading = 'planned' | 'good' | 'bad' | 'unknown' | 'worked' | 'failed' | 'unclear'

const READING: Record<Reading, { label: string; ink: string; surface: string; bar: string }> = {
    planned: { label: 'Set the check', ink: 'text-primary', surface: 'bg-surface-secondary', bar: 'bg-primary' },
    good: { label: 'Looks good so far', ink: 'text-success', surface: 'bg-success-highlight', bar: 'bg-success' },
    bad: { label: 'Still happening', ink: 'text-danger', surface: 'bg-danger-highlight', bar: 'bg-danger' },
    unknown: { label: 'Not enough proof', ink: 'text-primary', surface: 'bg-surface-secondary', bar: 'bg-primary' },
    worked: { label: 'Worked', ink: 'text-success', surface: 'bg-success-highlight', bar: 'bg-success' },
    failed: { label: "Didn't work", ink: 'text-danger', surface: 'bg-danger-highlight', bar: 'bg-danger' },
    unclear: { label: "Can't tell", ink: 'text-primary', surface: 'bg-surface-secondary', bar: 'bg-primary' },
}

function readingFor(example: ImpactFollowUpExample, stage: FollowUpStage): Reading {
    if (stage === 'planned') {
        return 'planned'
    }
    if (stage === 'finished') {
        return example.verdict === 'met' ? 'worked' : example.verdict === 'failed' ? 'failed' : 'unclear'
    }
    return example.watchingSignal === 'promising' ? 'good' : example.watchingSignal === 'risk' ? 'bad' : 'unknown'
}

export interface ImpactFollowUpConceptProps {
    example: ImpactFollowUpExample
    stage: FollowUpStage
    version: 'poster' | 'queue' | 'tape' | 'poster-runway'
}

export function ImpactFollowUpConcept({ example, stage, version }: ImpactFollowUpConceptProps): JSX.Element {
    const [trackingEnabled, setTrackingEnabled] = useState(false)
    const [editing, setEditing] = useState(false)
    const [suggestion, setSuggestion] = useState('')
    const [drafted, setDrafted] = useState(false)
    const [actionTaken, setActionTaken] = useState(false)
    const reading = readingFor(example, stage)
    const tone = READING[reading]
    const elapsed = stage === 'planned' ? 0 : stage === 'watching' ? example.elapsedDays : example.windowDays
    const observed = stage === 'planned' ? 0 : stage === 'watching' ? example.watchingSample : example.finishedSample
    const daysLeft = Math.max(0, example.windowDays - elapsed)
    const casesLeft = Math.max(0, example.sampleNeeded - observed)
    const timePercent = Math.min(100, (elapsed / example.windowDays) * 100)
    const casesPercent = Math.min(100, (observed / example.sampleNeeded) * 100)
    const missingCheck =
        stage === 'planned' || example.watchingSignal === 'no_trial'
            ? undefined
            : example.evidence.find(
                  (check) => (stage === 'watching' ? check.watchingResult : check.result) === 'missing'
              )
    const missingSignal = Boolean(missingCheck)
    const result =
        stage === 'planned' ? example.baseline : stage === 'watching' ? example.watchingValue : example.finishedValue
    const summary =
        stage === 'planned' ? example.goalShort : stage === 'watching' ? example.watchingNote : example.resultNote
    const statusIcon =
        reading === 'worked' ? (
            <IconCheckCircle />
        ) : reading === 'bad' || reading === 'failed' ? (
            <IconWarning />
        ) : reading === 'unknown' || reading === 'unclear' ? (
            <IconQuestion />
        ) : (
            <IconClock />
        )
    const stateLabel =
        stage === 'planned' ? 'Before release' : stage === 'watching' ? 'Watching impact' : 'Window closed'
    const readinessText =
        stage === 'planned'
            ? `After release: ${example.windowDays} days and ${example.sampleNeeded} ${example.sampleLabel.toLowerCase()}`
            : stage === 'watching'
              ? `${daysLeft} ${daysLeft === 1 ? 'day' : 'days'} left · ${casesLeft} more ${example.sampleLabel.toLowerCase()} needed${missingSignal ? ' · a check has no data' : ''}`
              : missingSignal
                ? `Window ended · a check has no data${casesLeft ? ` · ${casesLeft} ${example.sampleLabel.toLowerCase()} missing` : ''}`
                : casesLeft
                  ? `Window ended · ${casesLeft} ${example.sampleLabel.toLowerCase()} missing`
                  : 'Window ended · enough time and cases to judge'
    const nextProof =
        stage === 'planned'
            ? `Check after ${example.windowDays} days`
            : stage === 'watching'
              ? `${casesLeft ? `${casesLeft} more ${example.sampleLabel.toLowerCase()}` : 'Enough qualifying cases'}${missingCheck ? ` · missing ${missingCheck.signal.toLowerCase()}` : ''}`
              : missingCheck
                ? `Missing ${missingCheck.signal.toLowerCase()}`
                : casesLeft
                  ? `${casesLeft} ${example.sampleLabel.toLowerCase()} missing`
                  : 'Proof complete'

    const measurementActions = (
        <div className="flex flex-wrap items-center gap-3 text-xs">
            <LemonButton type="secondary" size="small" onClick={() => setEditing(!editing)}>
                {editing ? 'Close suggestion' : 'Change how we measure this'}
            </LemonButton>
            {stage === 'planned' && (
                <LemonSwitch
                    checked={trackingEnabled}
                    onChange={setTrackingEnabled}
                    label="Follow up after release"
                    size="small"
                />
            )}
            {trackingEnabled && stage === 'planned' && <span className="text-secondary">On in this preview only</span>}
            {stage === 'finished' && example.verdict !== 'met' && (
                <LemonButton type="secondary" size="small" onClick={() => setActionTaken(true)}>
                    {example.verdict === 'failed' ? 'Draft a follow-up report' : 'Plan another check'}
                </LemonButton>
            )}
            {actionTaken && <span className="text-secondary">Preview only · no report created</span>}
        </div>
    )

    const evidence = (
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
            {example.evidence.map((check) => {
                const state =
                    stage === 'planned' ? 'waiting' : stage === 'watching' ? check.watchingResult : check.result
                return (
                    <div key={check.signal} className="flex items-center gap-2">
                        <span
                            className={
                                state === 'met' ? 'text-success' : state === 'failed' ? 'text-danger' : 'text-secondary'
                            }
                            aria-hidden="true"
                        >
                            {state === 'met' ? '●' : state === 'failed' ? '✕' : '○'}
                        </span>
                        <span>
                            {check.signal}:{' '}
                            <strong>
                                {stage === 'planned'
                                    ? check.baseline
                                    : stage === 'watching'
                                      ? check.watching
                                      : check.finished}
                            </strong>{' '}
                            / {check.target}
                        </span>
                    </div>
                )
            })}
        </div>
    )

    const footer = (
        <div className="flex flex-col gap-3 border-t border-primary px-4 py-3">
            {measurementActions}
            {editing && (
                <div className="flex flex-col gap-2 rounded border border-primary bg-surface-secondary p-3">
                    <label htmlFor={`suggest-${version}-${stage}-${example.id}`} className="text-sm font-semibold">
                        What should we check instead?
                    </label>
                    <textarea
                        id={`suggest-${version}-${stage}-${example.id}`}
                        className="w-full rounded border border-primary bg-surface-primary p-2 text-sm"
                        rows={2}
                        placeholder="For example: Count affected users, not page loads, and wait for at least 30 users."
                        value={suggestion}
                        onChange={(event) => {
                            setSuggestion(event.target.value)
                            setDrafted(false)
                        }}
                    />
                    <div>
                        <LemonButton
                            type="primary"
                            size="small"
                            disabled={!suggestion.trim()}
                            onClick={() => setDrafted(true)}
                        >
                            Ask an agent to draft the check
                        </LemonButton>
                    </div>
                    {drafted && (
                        <div role="status" className="text-xs">
                            Preview only · an agent would turn “{suggestion}” into a query and ask you to review it. No
                            request was sent.
                        </div>
                    )}
                </div>
            )}
            {stage === 'finished' && example.verdict !== 'met' && (
                <details className="text-xs">
                    <summary className="cursor-pointer">
                        Why {reading === 'failed' ? 'did it fail' : 'can’t we tell'}?
                    </summary>
                    <p className="mb-0 mt-2">
                        {example.reason} {example.nextStep}
                    </p>
                </details>
            )}
            <details className="text-xs">
                <summary className="cursor-pointer text-secondary">How we measure this · view query</summary>
                <p className="my-2">
                    After: {example.releaseGate}. Need: {example.minimumEvidence}. {example.window}.
                </p>
                <pre className="m-0 overflow-x-auto rounded border border-primary bg-surface-primary p-3">
                    <code>{example.query}</code>
                </pre>
                <p className="mb-0 mt-2">Illustrative query and invented data. Not a live check.</p>
            </details>
        </div>
    )

    const tracks = (
        <div className="grid gap-2 text-xs sm:grid-cols-2" aria-label={readinessText}>
            {[
                { label: 'Time', value: `${elapsed}/${example.windowDays} days`, percent: timePercent },
                { label: example.sampleLabel, value: `${observed}/${example.sampleNeeded}`, percent: casesPercent },
            ].map((track) => (
                <div key={track.label}>
                    <div className="mb-1 flex justify-between gap-2">
                        <span>{track.label}</span>
                        <strong>{track.value}</strong>
                    </div>
                    <div
                        className="h-2 overflow-hidden rounded-full bg-surface-secondary"
                        role="progressbar"
                        aria-label={track.label}
                        aria-valuenow={Math.round(track.percent)}
                        aria-valuemin={0}
                        aria-valuemax={100}
                    >
                        <div className={`h-full rounded-full ${tone.bar}`} style={{ width: `${track.percent}%` }} />
                    </div>
                </div>
            ))}
        </div>
    )

    const runway = version === 'poster-runway' && (
        <div className="grid gap-4 border-t border-primary bg-surface-secondary px-5 py-4 md:grid-cols-[minmax(8rem,0.7fr)_minmax(0,2fr)_minmax(10rem,0.9fr)] md:items-center">
            <div>
                <div className="text-xs text-secondary">Decision {example.decisionDate}</div>
                <strong className="block text-lg leading-tight">
                    {stage === 'planned'
                        ? 'Starts at release'
                        : stage === 'watching'
                          ? `${daysLeft} ${daysLeft === 1 ? 'day' : 'days'} left`
                          : 'Window ended'}
                </strong>
            </div>
            <div className="min-w-0">
                <div className="mb-2 flex items-center justify-between gap-2 text-xs">
                    <span>Release</span>
                    <strong>{elapsed} / {example.windowDays} days elapsed</strong>
                    <span>Decision</span>
                </div>
                <div className="flex gap-1 overflow-x-auto pb-1">
                    {Array.from({ length: example.windowDays }, (_, index) => {
                        const value = example.afterTrend[index]
                        const observedDay = index < elapsed
                        const hasData = observedDay && value !== undefined && !Number.isNaN(value)
                        return (
                            <div
                                key={index}
                                className={`flex min-w-8 grow flex-col items-center justify-center rounded border px-1 py-1 leading-none ${observedDay ? 'border-primary bg-surface-primary' : 'border-dashed border-primary text-secondary'}`}
                                aria-label={`Day ${index + 1}: ${hasData ? value : observedDay ? 'no data' : 'not yet measured'}`}
                            >
                                <span className="text-[10px]">{index + 1}</span>
                                <strong className="mt-1 text-sm">{hasData ? value : observedDay ? '?' : '·'}</strong>
                            </div>
                        )
                    })}
                </div>
                <div className="mt-1 text-[11px] text-secondary">
                    {example.chartLabel} · ? = no data
                </div>
            </div>
            <div className="text-sm">
                <div className="text-xs text-secondary">Evidence collected</div>
                <strong className="block text-base">
                    {observed} / {example.sampleNeeded} {example.sampleLabel.toLowerCase()}
                </strong>
                <div className="text-xs">{nextProof}</div>
            </div>
        </div>
    )

    if (version === 'queue') {
        return (
            <article
                aria-label={`${example.title}: ${tone.label}`}
                className="overflow-hidden rounded border border-primary bg-surface-primary"
            >
                <div className="grid items-center gap-x-4 gap-y-2 p-3 md:grid-cols-[minmax(8rem,1fr)_minmax(9rem,1fr)_minmax(11rem,1fr)_minmax(12rem,1.3fr)]">
                    <div>
                        <div className="text-xs text-secondary">{example.title}</div>
                        <h2 className="m-0 text-sm font-semibold">{example.outcome}</h2>
                    </div>
                    <div className={`flex items-center gap-2 text-lg font-black ${tone.ink}`}>
                        <span className="[&_svg]:size-5">{statusIcon}</span>
                        {tone.label}
                    </div>
                    <div className="text-sm">
                        <div className="text-xs text-secondary">Before → now → goal</div>
                        <strong>
                            {example.baseline} → {stage === 'planned' ? '—' : result} → {example.goalShort}
                        </strong>
                    </div>
                    <div>
                        {tracks}
                        <div className="mt-1 text-xs font-medium">{readinessText}</div>
                    </div>
                </div>
                {footer}
            </article>
        )
    }

    if (version === 'tape') {
        return (
            <article
                aria-label={`${example.title}: ${tone.label}`}
                className="overflow-hidden rounded border border-primary bg-surface-primary"
            >
                <div className="grid md:grid-cols-[minmax(0,1fr)_12rem]">
                    <div className="min-w-0 p-5">
                        <h2 className="m-0 text-base font-semibold">{example.outcome}</h2>
                        <div className="mt-1 text-sm">
                            A win means <strong>{example.goalShort}</strong>
                        </div>
                        <div className="mt-5 text-xs text-secondary">{example.chartLabel} · each day after release</div>
                        <div className="mt-2 overflow-x-auto">
                            <div
                                className="grid gap-1"
                                style={{
                                    gridTemplateColumns: `repeat(${example.windowDays}, minmax(0, 1fr))`,
                                    minWidth: example.windowDays * 35,
                                }}
                            >
                                {Array.from({ length: example.windowDays }, (_, index) => {
                                    const value = example.afterTrend[index]
                                    const observedDay = index < elapsed
                                    const hasData = observedDay && value !== undefined && !Number.isNaN(value)
                                    const meetsDailyGoal =
                                        hasData && example.chartGoal !== null && value === example.chartGoal
                                    const missesDailyGoal =
                                        hasData && example.chartGoal !== null && value !== example.chartGoal
                                    return (
                                        <div key={index} className="min-w-0 text-center">
                                            <div
                                                className={`flex h-12 items-center justify-center rounded border-2 text-sm font-bold ${meetsDailyGoal ? 'border-success text-success' : missesDailyGoal ? 'border-danger text-danger' : 'border-primary text-secondary'} ${observedDay ? 'bg-surface-secondary' : 'border-dashed'}`}
                                                aria-label={`Day ${index + 1}: ${hasData ? value : observedDay ? 'no data' : 'not yet measured'}`}
                                            >
                                                {hasData ? value : observedDay ? '?' : '·'}
                                            </div>
                                            <div className="mt-1 text-[10px]">{index + 1}</div>
                                        </div>
                                    )
                                })}
                            </div>
                        </div>
                        <div className="mt-3 text-xs text-secondary">
                            Numbers show the daily signal, not the final verdict. ? means no data.
                        </div>
                    </div>
                    <div
                        className={`flex flex-col justify-between gap-3 border-t border-primary p-5 md:border-l md:border-t-0 ${tone.surface}`}
                    >
                        <div>
                            <div className="text-xs">{stateLabel}</div>
                            <strong className={`mt-2 block text-2xl leading-tight ${tone.ink}`}>{tone.label}</strong>
                        </div>
                        <div>
                            <strong className="block text-lg">
                                {stage === 'planned'
                                    ? 'Starts at release'
                                    : stage === 'watching'
                                      ? `${daysLeft} ${daysLeft === 1 ? 'day' : 'days'} left`
                                      : 'Window ended'}
                            </strong>
                            <span className="text-xs">
                                {nextProof} · {example.decisionDate}
                            </span>
                        </div>
                    </div>
                </div>
                {footer}
            </article>
        )
    }

    return (
        <article
            aria-label={`${example.title}: ${tone.label}`}
            className="overflow-hidden rounded border border-primary bg-surface-primary"
        >
            <div className="grid md:grid-cols-[minmax(13rem,0.85fr)_minmax(0,1.15fr)]">
                <div className={`flex flex-col justify-between gap-5 p-6 ${tone.surface}`}>
                    <div>
                        <span className="text-xs">
                            {example.title} · {stateLabel}
                        </span>
                        <h2 className={`m-0 mt-3 text-4xl font-black leading-none ${tone.ink}`}>{tone.label}</h2>
                        <p className="mb-0 mt-2 text-sm">{example.outcome}</p>
                    </div>
                    <div>
                        <div className="text-xs">To call this a win</div>
                        <strong className="text-lg">{example.goalShort}</strong>
                        {version === 'poster' && <div className="mt-2 text-xs">{readinessText}</div>}
                    </div>
                </div>
                <div className="flex flex-col justify-between gap-3 p-5">
                    <ImpactTrendChart example={example} stage={stage} />
                    <div className="flex items-center justify-between gap-3 border-t border-primary pt-2 text-sm">
                        <span>
                            Before: <strong>{example.baseline}</strong>
                        </span>
                        <span>
                            After: <strong>{stage === 'planned' ? 'waiting for release' : result}</strong>
                        </span>
                    </div>
                    {evidence}
                    {version === 'poster' && <span className="text-xs text-secondary">{summary}</span>}
                </div>
            </div>
            {runway}
            {footer}
        </article>
    )
}
