import './ShipIt.scss'

import { useCallback, useEffect, useRef, useState } from 'react'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { SceneExport } from 'scenes/sceneTypes'

import {
    createInitialState,
    GameState,
    isMergeable,
    isOver,
    ITEMS,
    LANE_COUNT,
    moveLane,
    QUEUE_HOLD_MS,
    REQUIRED_APPROVALS,
    STALENESS_LIMIT,
    step,
} from './shipItGame'

/** A frame longer than this means the tab was backgrounded, so hold the game where the player left it. */
const MAX_FRAME_MS = 100

const BEST_SCORE_KEY = 'ship-it-best-score'

function readBestScore(): number {
    try {
        return Number(localStorage.getItem(BEST_SCORE_KEY)) || 0
    } catch {
        return 0
    }
}

function writeBestScore(score: number): void {
    try {
        localStorage.setItem(BEST_SCORE_KEY, String(score))
    } catch {
        // A private window or a full store just costs the player their best score.
    }
}

/** The one thing between the pull request and the merge queue, which is what the player should chase next. */
function progressLabel(state: GameState): string {
    if (state.phase === 'queued') {
        return 'In the merge queue'
    }
    if (!state.ciGreen && state.approvals < REQUIRED_APPROVALS) {
        return 'Waiting on CI and reviews'
    }
    if (!state.ciGreen) {
        return 'Waiting on CI'
    }
    if (state.approvals < REQUIRED_APPROVALS) {
        return 'Waiting on reviews'
    }
    return 'Ready to merge'
}

function StatusBar({ state }: { state: GameState }): JSX.Element {
    const queueSecondsLeft = Math.max(0, Math.ceil((QUEUE_HOLD_MS - state.queueMs) / 1000))

    return (
        <div className="flex flex-wrap gap-2 items-center">
            <LemonTag type={state.ciGreen ? 'success' : 'danger'}>{state.ciGreen ? 'CI green' : 'CI red'}</LemonTag>
            <LemonTag type={state.approvals >= REQUIRED_APPROVALS ? 'success' : 'default'}>
                <span>Approvals&nbsp;</span>
                <span translate="no">
                    {state.approvals}/{REQUIRED_APPROVALS}
                </span>
            </LemonTag>
            <LemonTag type={state.staleness > 0 ? 'warning' : 'default'}>
                <span>Staleness&nbsp;</span>
                <span translate="no">
                    {state.staleness}/{STALENESS_LIMIT}
                </span>
            </LemonTag>
            {state.phase === 'queued' && (
                <LemonTag type="primary">
                    <span>Hold for&nbsp;</span>
                    <span translate="no">{queueSecondsLeft}s</span>
                </LemonTag>
            )}
        </div>
    )
}

function Track({ state }: { state: GameState }): JSX.Element {
    return (
        <div
            className="ShipIt__track"
            aria-hidden="true"
            style={{ '--ship-it-lanes': LANE_COUNT } as React.CSSProperties}
        >
            {Array.from({ length: LANE_COUNT }, (_, lane) => (
                <div key={lane} className="ShipIt__lane" />
            ))}
            {/* The number is the pull request that added this game, which is why it is written out rather than scored. */}
            <div
                className="ShipIt__pr"
                data-mergeable={isMergeable(state)}
                style={{ top: `${(state.lane + 0.5) * (100 / LANE_COUNT)}%` }}
            >
                #100001
            </div>
            {state.items.map((item) => (
                <div
                    key={item.id}
                    className="ShipIt__item"
                    data-kind={ITEMS[item.kind].good ? 'good' : 'bad'}
                    style={{
                        left: `${item.x * 100}%`,
                        top: `${(item.lane + 0.5) * (100 / LANE_COUNT)}%`,
                    }}
                >
                    {ITEMS[item.kind].chip}
                </div>
            ))}
        </div>
    )
}

function Overlay({
    state,
    started,
    best,
    onStart,
}: {
    state: GameState
    started: boolean
    best: number
    onStart: () => void
}): JSX.Element | null {
    if (!started) {
        return (
            <div className="ShipIt__overlay">
                <h2>Ship it</h2>
                <p>
                    Steer your pull request between lanes to pick up approvals and green CI, and to dodge conflicts,
                    flakes and the stale bot. It only moves toward the merge queue while CI is green and both approvals
                    hold.
                </p>
                <p className="ShipIt__hint">Arrow keys, W and S, or the buttons below.</p>
                <LemonButton type="primary" onClick={onStart}>
                    Open a pull request
                </LemonButton>
            </div>
        )
    }

    if (!isOver(state)) {
        return null
    }

    const score = Math.floor(state.score)
    const merged = state.phase === 'merged'

    return (
        <div className="ShipIt__overlay">
            <h2>{merged ? 'Merged' : 'Closed as stale'}</h2>
            <p>
                <span>{merged ? 'It landed. You scored ' : 'The stale bot got there first. You scored '}</span>
                <span translate="no">{score}</span>
                <span>{score >= best ? ', your best yet.' : '.'}</span>
            </p>
            <LemonButton type="primary" onClick={onStart}>
                {merged ? 'Open another' : 'Try again'}
            </LemonButton>
        </div>
    )
}

export function ShipIt(): JSX.Element {
    const [state, setState] = useState<GameState>(createInitialState)
    const [started, setStarted] = useState(false)
    const [best, setBest] = useState(readBestScore)
    const boardRef = useRef<HTMLDivElement>(null)

    const running = started && !isOver(state)

    const start = useCallback((): void => {
        setState(createInitialState())
        setStarted(true)
        boardRef.current?.focus()
    }, [])

    const move = useCallback((delta: number): void => setState((current) => moveLane(current, delta)), [])

    useEffect(() => {
        if (!running) {
            return
        }
        let frame = 0
        let previous = performance.now()

        const tick = (now: number): void => {
            const dtMs = Math.min(MAX_FRAME_MS, now - previous)
            previous = now
            setState((current) => step(current, dtMs, Math.random))
            frame = requestAnimationFrame(tick)
        }

        frame = requestAnimationFrame(tick)
        return () => cancelAnimationFrame(frame)
    }, [running])

    useEffect(() => {
        if (!isOver(state)) {
            return
        }
        const score = Math.floor(state.score)
        if (score > best) {
            setBest(score)
            writeBestScore(score)
        }
    }, [state, best])

    const onKeyDown = (event: React.KeyboardEvent): void => {
        const key = event.key.toLowerCase()
        if (key === 'arrowup' || key === 'w') {
            event.preventDefault()
            move(-1)
        } else if (key === 'arrowdown' || key === 's') {
            event.preventDefault()
            move(1)
        } else if ((key === 'enter' || key === ' ') && !running) {
            event.preventDefault()
            start()
        }
    }

    return (
        <div className="ShipIt">
            <div className="flex flex-wrap gap-2 justify-between items-center">
                <StatusBar state={state} />
                <div className="flex gap-2 items-center">
                    <LemonTag type="muted">
                        <span>Score&nbsp;</span>
                        <span translate="no">{Math.floor(state.score)}</span>
                    </LemonTag>
                    {best > 0 && (
                        <LemonTag type="muted">
                            <span>Best&nbsp;</span>
                            <span translate="no">{best}</span>
                        </LemonTag>
                    )}
                </div>
            </div>

            <div>
                <div className="flex gap-2 justify-between items-center text-xs text-secondary mb-1">
                    <span>{progressLabel(state)}</span>
                    <span translate="no">{Math.floor(state.progress)}%</span>
                </div>
                <LemonProgress percent={state.progress} smoothing={false} size="large" />
            </div>

            <div
                className="ShipIt__board"
                ref={boardRef}
                tabIndex={0}
                role="application"
                aria-label="Ship it, a game about landing a pull request"
                onKeyDown={onKeyDown}
            >
                <Track state={state} />
                <Overlay state={state} started={started} best={best} onStart={start} />
            </div>

            <div className="flex flex-wrap gap-2 justify-between items-center">
                <div className="ShipIt__event" aria-live="polite">
                    {state.lastEvent ?? 'Waiting for review'}
                </div>
                <div className="flex gap-2">
                    <LemonButton
                        icon={<IconArrowUp />}
                        onClick={() => move(-1)}
                        disabledReason={running ? undefined : 'Open a pull request first'}
                        aria-label="Move up a lane"
                    />
                    <LemonButton
                        icon={<IconArrowDown />}
                        onClick={() => move(1)}
                        disabledReason={running ? undefined : 'Open a pull request first'}
                        aria-label="Move down a lane"
                    />
                </div>
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: ShipIt,
}
