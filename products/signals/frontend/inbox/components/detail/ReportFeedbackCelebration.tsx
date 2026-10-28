import './ReportFeedbackCelebration.scss'

import { useEffect, useState } from 'react'

import * as partyPng from '@posthog/brand/hoggies/png/party'

import { pngHoggie } from 'lib/brand/hoggies'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

const HedgehogParty = pngHoggie(partyPng)

/** Covers the pop, the hold, and the fade in the scss keyframes, plus a short tail. */
export const CELEBRATION_DURATION_MS = 1100

// Fixed scatter so Storybook and tests render the same picture every time.
const CONFETTI = [
    { dx: -54, dy: -48, rot: 300, delay: 0, color: '#f54e00' },
    { dx: -34, dy: -74, rot: 180, delay: 30, color: '#f9bd2b' },
    { dx: -10, dy: -88, rot: 110, delay: 10, color: '#1d4aff' },
    { dx: 14, dy: -84, rot: 250, delay: 50, color: '#000000' },
    { dx: 38, dy: -70, rot: 150, delay: 20, color: '#f54e00' },
    { dx: 58, dy: -44, rot: 320, delay: 60, color: '#f9bd2b' },
    { dx: -46, dy: -20, rot: 80, delay: 80, color: '#1d4aff' },
    { dx: 50, dy: -16, rot: 210, delay: 70, color: '#f9bd2b' },
]

function prefersReducedMotion(): boolean {
    return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

/**
 * A party hog that pops up above the thumbs-up button, with a small confetti scatter, then
 * removes itself. Render it inside a `relative` wrapper around the button: the row reflows when
 * "Add a note" appears after the click, and the hog has to move with the thumb.
 */
export function ReportFeedbackCelebration({ onDone }: { onDone: () => void }): JSX.Element {
    useOnMountEffect(() => {
        const timer = window.setTimeout(onDone, CELEBRATION_DURATION_MS)
        return () => window.clearTimeout(timer)
    })

    return (
        <span className="ReportFeedbackCelebration" aria-hidden="true" data-attr="inbox-report-feedback-celebration">
            {CONFETTI.map((piece, index) => (
                <span
                    key={index}
                    className="ReportFeedbackCelebration__confetti"
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
            <HedgehogParty className="ReportFeedbackCelebration__hog" size={72} loading="eager" />
        </span>
    )
}

/**
 * Shared by every feedback footer, so the flag, the reduced-motion check, and the once-per-rating
 * rule hold on each surface. The celebration is view-only, so it stays in local state and only
 * the instance that was clicked pops.
 */
export function useReportFeedbackCelebration(): { celebrate: () => void; celebration: JSX.Element | null } {
    const enabled = useFeatureFlag('INBOX_REPORT_FEEDBACK_BANG')
    const [activeId, setActiveId] = useState<number | null>(null)

    useEffect(() => {
        // The pop lasts about a second, so a first-time fetch of the hog image would miss it.
        if (enabled) {
            new Image().src = partyPng.src
        }
    }, [enabled])

    const celebrate = (): void => {
        if (enabled && !prefersReducedMotion()) {
            setActiveId(Date.now())
        }
    }

    const celebration =
        activeId !== null ? <ReportFeedbackCelebration key={activeId} onDone={() => setActiveId(null)} /> : null

    return { celebrate, celebration }
}
