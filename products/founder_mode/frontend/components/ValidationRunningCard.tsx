import { useEffect, useState } from 'react'

import { IconCheck } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { ValidationPass } from './founderValidationLogic'

// Stage labels keyed by the backend's `current_pass` value, so the card mirrors the actual
// Celery task state instead of guessing from elapsed time.
const PASSES: { key: ValidationPass; label: string }[] = [
    { key: 'research', label: 'Researching real competitors' },
    { key: 'synthesis', label: 'Synthesizing assumptions, experiments, and verdict' },
]

export function ValidationRunningCard({
    startedAt,
    currentPass,
}: {
    startedAt: string | undefined
    currentPass: ValidationPass | undefined
}): JSX.Element {
    const elapsedMs = useElapsedMs(startedAt)
    const activeIndex = PASSES.findIndex((p) => p.key === currentPass)

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
                        {PASSES.map((pass, i) => (
                            <ProgressStep
                                key={pass.key}
                                label={pass.label}
                                state={
                                    activeIndex < 0
                                        ? 'pending'
                                        : i < activeIndex
                                          ? 'done'
                                          : i === activeIndex
                                            ? 'active'
                                            : 'pending'
                                }
                            />
                        ))}
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
