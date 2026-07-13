import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconCheckCircle, IconCircleDashed, IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { observationProgressLogic } from '../observations/observationProgressLogic'

// Mirrors the backend OBSERVATION_PHASE_ORDER; the live phase arrives over SSE via observationProgressLogic.
const PHASE_ORDER = ['queued', 'fetching', 'rendering', 'uploading', 'analyzing', 'finalizing'] as const
type Phase = (typeof PHASE_ORDER)[number]

const PHASE_LABELS: Record<Phase, string> = {
    queued: 'Queued',
    fetching: 'Fetching events',
    rendering: 'Rendering video',
    uploading: 'Uploading video for analysis',
    analyzing: 'Analyzing recording',
    finalizing: 'Finalizing',
}

// Per-phase time constants (seconds) for an asymptotic fill (~63% at tau, ~86% at 2*tau) so the bar keeps moving.
const PHASE_TAU_S: Record<Phase, number> = {
    queued: 4,
    fetching: 4,
    rendering: 30,
    uploading: 6,
    analyzing: 30,
    finalizing: 5,
}

type PhaseStatus = 'done' | 'active' | 'pending'

function asymptoticFillPercent(elapsedSeconds: number, tauSeconds: number): number {
    return (1 - Math.exp(-elapsedSeconds / tauSeconds)) * 100
}

function phaseStatusAt(phaseIndex: number, currentStep: number): PhaseStatus {
    if (phaseIndex < currentStep) {
        return 'done'
    }
    return phaseIndex === currentStep ? 'active' : 'pending'
}

function PhaseStatusIcon({ status }: { status: PhaseStatus }): JSX.Element {
    if (status === 'done') {
        return <IconCheckCircle className="text-success text-base shrink-0" />
    }
    if (status === 'active') {
        return <Spinner className="text-base shrink-0" />
    }
    return <IconCircleDashed className="text-muted-alt text-base shrink-0" />
}

/**
 * Live progress for an in-progress observation, driven by the SSE stream in observationProgressLogic. Phase
 * boundaries are server-truthful; the rendering phase shows real frame counts, other phases an asymptotic
 * time-based fill. `compact` (dock) renders a single bar + label; otherwise a per-phase breakdown (details page).
 */
export function ObservationProgressBar({
    observationId,
    sessionId,
    compact = false,
}: {
    observationId: string
    sessionId: string
    compact?: boolean
}): JSX.Element {
    const { progress, streamError } = useValues(observationProgressLogic({ observationId, sessionId }))
    const { startStream } = useActions(observationProgressLogic({ observationId, sessionId }))
    usePeriodicRerender(1000)

    // The bar only renders for in-flight observations, so its mount is the signal to open the stream.
    useOnMountEffect(() => startStream())

    const currentStep = Math.min(progress?.step ?? 0, PHASE_ORDER.length - 1)
    const activePhase = PHASE_ORDER[currentStep]

    // Record when the active phase was first observed so its asymptotic fill animates from then.
    const startTimesRef = useRef<Record<number, number>>({})
    if (!(currentStep in startTimesRef.current)) {
        startTimesRef.current[currentStep] = Date.now()
    }
    const activeElapsed = Math.max(0, (Date.now() - startTimesRef.current[currentStep]) / 1000)

    // Real sub-progress only exists while rendering (frame counts from the rasterizer heartbeats); else asymptote.
    const frame = activePhase === 'rendering' ? progress?.rasterizer?.frame_progress : undefined
    const activeFill =
        frame && frame.estimatedTotalFrames > 0
            ? Math.min((frame.frame / frame.estimatedTotalFrames) * 100, 100)
            : asymptoticFillPercent(activeElapsed, PHASE_TAU_S[activePhase])

    if (streamError) {
        // The stream died but the observation may still be running — status polling keeps the page truthful.
        return (
            <div className="flex items-center gap-2 text-muted text-sm">
                <IconWarning className="text-warning text-base shrink-0" />
                <span>Live progress unavailable: {streamError}</span>
            </div>
        )
    }

    if (compact) {
        const detail =
            frame && frame.estimatedTotalFrames > 0 ? ` (${frame.frame} / ${frame.estimatedTotalFrames} frames)` : ''
        const overallPercent = ((currentStep + activeFill / 100) / PHASE_ORDER.length) * 100
        return (
            <div className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2 text-muted text-sm">
                    <Spinner textColored />
                    <span>
                        {PHASE_LABELS[activePhase]}
                        {detail}…
                    </span>
                </div>
                <LemonProgress percent={overallPercent} />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {PHASE_ORDER.map((phase, i) => {
                const status = phaseStatusAt(i, currentStep)
                const barPercent = status === 'done' ? 100 : status === 'active' ? activeFill : 0
                const detail =
                    phase === 'rendering' && status === 'active' && frame && frame.estimatedTotalFrames > 0
                        ? `${frame.frame} / ${frame.estimatedTotalFrames} frames`
                        : null
                return (
                    <div key={phase} className={`flex flex-col gap-1${status === 'pending' ? ' opacity-50' : ''}`}>
                        <div className="flex items-center gap-2 text-xs">
                            <PhaseStatusIcon status={status} />
                            <span className="truncate">
                                {PHASE_LABELS[phase]}
                                {detail ? <span className="text-muted-alt">&nbsp;({detail})</span> : null}
                            </span>
                        </div>
                        <div className="pl-6">
                            <LemonProgress percent={barPercent} />
                        </div>
                    </div>
                )
            })}
        </div>
    )
}
