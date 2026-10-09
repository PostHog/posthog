import './ReportFeedbackBang.scss'

import { useEffect } from 'react'
import { createPortal } from 'react-dom'

/** Covers the pop, the hold, and the fade in the scss keyframes, plus a short tail. */
export const BANG_DURATION_MS = 1300

export interface ReportFeedbackBangProps {
    /** Viewport centre of the thumbs-up button, in px. */
    origin: { x: number; y: number }
    onDone: () => void
}

interface ConfettiPiece {
    dx: number
    dy: number
    rot: number
    delay: number
    color: string
}

// Fixed scatter so Storybook and tests render the same picture every time.
const CONFETTI: ConfettiPiece[] = [
    { dx: -92, dy: -74, rot: 310, delay: 0, color: '#f54e00' },
    { dx: -70, dy: -118, rot: 200, delay: 40, color: '#f9bd2b' },
    { dx: -44, dy: -140, rot: 120, delay: 20, color: '#1d4aff' },
    { dx: -18, dy: -156, rot: 260, delay: 60, color: '#000000' },
    { dx: 14, dy: -150, rot: 160, delay: 10, color: '#f54e00' },
    { dx: 42, dy: -136, rot: 330, delay: 50, color: '#f9bd2b' },
    { dx: 72, dy: -112, rot: 90, delay: 30, color: '#1d4aff' },
    { dx: 96, dy: -70, rot: 230, delay: 70, color: '#000000' },
    { dx: -112, dy: -30, rot: 140, delay: 80, color: '#f9bd2b' },
    { dx: 110, dy: -26, rot: 300, delay: 90, color: '#f54e00' },
    { dx: -58, dy: -58, rot: 70, delay: 110, color: '#1d4aff' },
    { dx: 60, dy: -54, rot: 190, delay: 100, color: '#f9bd2b' },
    { dx: -30, dy: -96, rot: 350, delay: 130, color: '#000000' },
    { dx: 30, dy: -92, rot: 40, delay: 120, color: '#f54e00' },
    { dx: -84, dy: -4, rot: 280, delay: 150, color: '#1d4aff' },
    { dx: 86, dy: 2, rot: 110, delay: 140, color: '#f9bd2b' },
]

function starPoints(outer: number, inner: number, count: number, cx: number, cy: number, phase = 0): string {
    const points: string[] = []
    for (let i = 0; i < count * 2; i++) {
        const radius = i % 2 === 0 ? outer : inner
        const angle = (Math.PI * i) / count + phase
        points.push(`${(cx + radius * Math.cos(angle)).toFixed(1)},${(cy + radius * Math.sin(angle)).toFixed(1)}`)
    }
    return points.join(' ')
}

const OUTER_STAR = starPoints(118, 78, 16, 120, 70, -0.1)
const INNER_STAR = starPoints(96, 62, 12, 120, 70, 0.15)

/**
 * Comic "BANGER!" starburst with a confetti scatter, anchored just above the thumbs-up button.
 * Renders in a body portal so the scrolling report pane cannot clip it. Decorative only: the
 * footer never mounts it for readers who prefer reduced motion, and it unmounts itself when the
 * animation ends.
 */
export function ReportFeedbackBang({ origin, onDone }: ReportFeedbackBangProps): JSX.Element {
    useEffect(() => {
        const timer = window.setTimeout(onDone, BANG_DURATION_MS)
        return () => window.clearTimeout(timer)
    }, [onDone])

    return createPortal(
        <div className="ReportFeedbackBang" aria-hidden="true" data-attr="inbox-report-feedback-bang">
            <div
                className="ReportFeedbackBang__anchor"
                // The anchor follows the clicked button, so its position cannot be a static class.
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: origin.x, top: origin.y }}
            >
                {CONFETTI.map((piece, index) => (
                    <span
                        key={index}
                        className="ReportFeedbackBang__confetti"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={
                            {
                                '--dx': `${piece.dx}px`,
                                '--dy': `${piece.dy}px`,
                                '--rot': `${piece.rot}deg`,
                                '--delay': `${piece.delay}ms`,
                                backgroundColor: piece.color,
                            } as React.CSSProperties
                        }
                    />
                ))}
                <svg className="ReportFeedbackBang__burst" viewBox="-4 -52 248 244" width="190" height="187">
                    <polygon points={OUTER_STAR} fill="#f54e00" stroke="#000" strokeWidth="3" strokeLinejoin="round" />
                    <polygon
                        points={INNER_STAR}
                        fill="#f9bd2b"
                        stroke="#000"
                        strokeWidth="2.5"
                        strokeLinejoin="round"
                    />
                    <text
                        className="ReportFeedbackBang__text"
                        x="120"
                        y="88"
                        textAnchor="middle"
                        transform="rotate(-8 120 70)"
                    >
                        BANGER!
                    </text>
                </svg>
            </div>
        </div>,
        document.body
    )
}
