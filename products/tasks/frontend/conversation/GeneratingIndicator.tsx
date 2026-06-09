import { JSX, useEffect, useRef, useState } from 'react'

import { IconBrain } from './primitives/icons'

const THINKING_MESSAGES = [
    'Booping',
    'Crunching',
    'Digging',
    'Fetching',
    'Inferring',
    'Indexing',
    'Juggling',
    'Noodling',
    'Peeking',
    'Percolating',
    'Poking',
    'Pondering',
    'Scanning',
    'Scrambling',
    'Sifting',
    'Sniffing',
    'Spelunking',
    'Tinkering',
    'Unraveling',
    'Decoding',
    'Trekking',
    'Sorting',
    'Trimming',
    'Mulling',
    'Surfacing',
    'Rummaging',
    'Scouting',
    'Scouring',
    'Threading',
    'Hunting',
    'Swizzling',
    'Grokking',
    'Hedging',
    'Scheming',
    'Unfurling',
    'Puzzling',
    'Dissecting',
    'Stacking',
    'Snuffling',
    'Hashing',
    'Clustering',
    'Teasing',
    'Cranking',
    'Merging',
    'Snooping',
    'Rewiring',
    'Bundling',
    'Linking',
    'Mapping',
    'Tickling',
    'Flicking',
    'Hopping',
    'Rolling',
    'Zipping',
    'Twisting',
    'Blooming',
    'Sparking',
    'Nesting',
    'Looping',
    'Wiring',
    'Snipping',
    'Zoning',
    'Tracing',
    'Warping',
    'Twinkling',
    'Flipping',
    'Priming',
    'Snagging',
    'Scuttling',
    'Framing',
    'Sharpening',
    'Flibbertigibbeting',
    'Kerfuffling',
    'Dithering',
    'Discombobulating',
    'Rambling',
    'Befuddling',
    'Waffling',
    'Muckling',
    'Hobnobbing',
    'Galumphing',
    'Puttering',
    'Whiffling',
    'Thinking',
]

function getRandomThinkingMessage(): string {
    return THINKING_MESSAGES[Math.floor(Math.random() * THINKING_MESSAGES.length)]
}

export function formatDuration(ms: number, fractionDigits = 2): string {
    const totalSeconds = Math.floor(ms / 1000)
    const mins = Math.floor(totalSeconds / 60)
    const secs = totalSeconds % 60

    if (mins > 0) {
        return `${mins}m ${secs.toString().padStart(2, '0')}s`
    }

    if (fractionDigits <= 0) {
        return `${secs}s`
    }

    const fractionalUnit = 10 ** (3 - fractionDigits)
    const fractionalValue = Math.floor((ms % 1000) / fractionalUnit)

    return `${secs}.${fractionalValue.toString().padStart(fractionDigits, '0')}s`
}

interface GeneratingIndicatorProps {
    /** Timestamp (ms) when the prompt started. Only render this component while a prompt is pending. */
    startedAt?: number | null
    /** Accumulated time (ms) spent waiting for user input, subtracted from elapsed display. */
    pausedDurationMs?: number
}

export function GeneratingIndicator({ startedAt, pausedDurationMs }: GeneratingIndicatorProps = {}): JSX.Element {
    const [elapsed, setElapsed] = useState(0)
    const [activity, setActivity] = useState(getRandomThinkingMessage)

    const pausedRef = useRef(pausedDurationMs ?? 0)
    pausedRef.current = pausedDurationMs ?? 0

    useEffect(() => {
        const startTime = startedAt ?? Date.now()
        const interval = setInterval(() => {
            setElapsed(Math.max(0, Date.now() - startTime - pausedRef.current))
        }, 50)

        return () => clearInterval(interval)
    }, [startedAt])

    useEffect(() => {
        const interval = setInterval(() => {
            setActivity(getRandomThinkingMessage())
        }, 2000)

        return () => clearInterval(interval)
    }, [])

    return (
        <div className="flex items-center gap-2 select-none" style={{ WebkitUserSelect: 'none' }}>
            <IconBrain className="ph-pulse text-default" style={{ fontSize: 12 }} />
            <span className="text-[13px] text-accent">{activity}...</span>
            <span className="text-[13px] text-muted">(Generating</span>
            <span className="mx-[2px] my-0 inline-block h-1 w-1 rounded-full bg-muted" />
            <span className="text-[13px] text-muted" style={{ fontVariantNumeric: 'tabular-nums' }}>
                {formatDuration(elapsed, 1)})
            </span>
        </div>
    )
}
