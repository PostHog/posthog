import { useEffect, useState } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { TaskRun } from '../types'

const REVEAL_DELAY_MS = 2000

interface CloudInitializingViewProps {
    run: TaskRun | null
}

function copyFor(stage: string | null): { heading: string; subtitle: string } {
    switch (stage) {
        case 'queued':
            return {
                heading: 'Waiting in the queue…',
                subtitle: 'Reserving a cloud sandbox — this can take a few seconds.',
            }
        case 'in_progress':
            return {
                heading: 'Starting the sandbox…',
                subtitle: 'Connecting to your cloud runner.',
            }
        default:
            return {
                heading: 'Getting things ready…',
                subtitle: 'Connecting to your cloud runner.',
            }
    }
}

export default function CloudInitializingView({ run }: CloudInitializingViewProps): JSX.Element {
    const { heading, subtitle } = copyFor(run?.stage ?? run?.status ?? null)

    // Show a bare spinner first so quick boots don't flash the full explainer.
    const [revealed, setRevealed] = useState(false)
    useEffect(() => {
        const timer = setTimeout(() => setRevealed(true), REVEAL_DELAY_MS)
        return () => clearTimeout(timer)
    }, [])

    if (!revealed) {
        return (
            <div className="flex h-full w-full items-center justify-center">
                <Spinner size="large" textColored />
            </div>
        )
    }

    return (
        <div className="flex h-full w-full flex-col items-center justify-center gap-4 p-4">
            <div className="flex flex-col items-center gap-2 text-center">
                <div className="flex items-center gap-2">
                    <Spinner textColored />
                    <span className="text-base font-medium">{heading}</span>
                </div>
                <span className="text-sm text-muted">{subtitle}</span>
            </div>
        </div>
    )
}
