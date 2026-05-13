import { useEffect, useState } from 'react'

import { IconCheck } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Spinner } from 'lib/lemon-ui/Spinner'

// Rough split between the two Gemini passes. The grounded research call is typically the
// slower of the two (search grounding adds latency); synthesis is faster but still streams
// structured JSON. This threshold is used only for the UI's staged progress indicator —
// the backend doesn't expose `current_pass` yet, so this is a heuristic.
const RESEARCH_THRESHOLD_MS = 22_000

export function ValidationRunningCard({ startedAt }: { startedAt: string | undefined }): JSX.Element {
    const elapsedMs = useElapsedMs(startedAt)
    const onSynthesis = elapsedMs >= RESEARCH_THRESHOLD_MS

    return (
        <LemonCard className="p-6">
            <div className="flex items-start gap-4">
                <Spinner size="large" />
                <div className="flex-1">
                    <h3 className="text-base font-semibold">Validating your idea</h3>
                    <p className="text-sm text-text-secondary mt-1">
                        Researching real competitors and synthesizing a structured report. Usually 30-60 seconds.
                    </p>

                    <ol className="mt-4 space-y-2">
                        <ProgressStep label="Researching real competitors" state={onSynthesis ? 'done' : 'active'} />
                        <ProgressStep
                            label="Synthesizing assumptions, experiments, and verdict"
                            state={onSynthesis ? 'active' : 'pending'}
                        />
                    </ol>

                    <p className="text-xs text-text-secondary mt-4 tabular-nums">Elapsed {formatElapsed(elapsedMs)}</p>
                </div>
            </div>
        </LemonCard>
    )
}

function ProgressStep({ label, state }: { label: string; state: 'done' | 'active' | 'pending' }): JSX.Element {
    const indicator =
        state === 'done' ? (
            <IconCheck className="w-4 h-4 text-success" />
        ) : state === 'active' ? (
            <Spinner size="small" textColored />
        ) : (
            <span className="w-4 h-4 inline-block rounded-full border border-border" />
        )
    const textClass = state === 'pending' ? 'text-text-secondary' : 'text-text-primary'
    return (
        <li className="flex items-center gap-3 text-sm">
            <span className="w-4 h-4 flex items-center justify-center">{indicator}</span>
            <span className={textClass}>{label}</span>
        </li>
    )
}

function useElapsedMs(startedAt: string | undefined): number {
    const [now, setNow] = useState(() => Date.now())
    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(id)
    }, [])
    if (!startedAt) {
        return 0
    }
    return Math.max(0, now - new Date(startedAt).getTime())
}

function formatElapsed(ms: number): string {
    const totalSeconds = Math.floor(ms / 1000)
    const minutes = Math.floor(totalSeconds / 60)
    const seconds = totalSeconds % 60
    return `${minutes}:${seconds.toString().padStart(2, '0')}`
}
