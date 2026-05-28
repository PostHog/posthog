/**
 * `<FocusModeBanner />` — thin top-of-main-area indicator that signals
 * to the user "the dock is currently authorized to navigate this
 * area for you" — and lets them toggle that permission inline.
 *
 * Visibility:
 *   - Only when the dock is in concierge mode (in playground the
 *     dock isn't driving the console; the toggle doesn't apply).
 *   - Stays visible whether focus mode is on OR paused, so the
 *     "the dock has permission to do this" surface is always
 *     reachable — only the styling changes.
 *
 * When the dock fires a focus event, the banner briefly elevates with
 * the most recent target so the user can see what just happened
 * underneath them.
 */

'use client'

import { EyeIcon, EyeOffIcon } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useDockStore } from './dock-context'
import { useFocusStore, type FocusTarget } from './focus-context'

/** Show the "just navigated" emphasis state for this many ms after a focus event. */
const RECENT_EVENT_WINDOW_MS = 2500

export function FocusModeBanner(): React.ReactElement | null {
    const { context } = useDockStore()
    const focus = useFocusStore()
    const [recent, setRecent] = useState<{ target: FocusTarget; at: number } | null>(null)

    useEffect(() => {
        if (!focus.target) {
            return
        }
        setRecent({ target: focus.target, at: Date.now() })
        const t = setTimeout(() => {
            setRecent((r) => (r && Date.now() - r.at >= RECENT_EVENT_WINDOW_MS ? null : r))
        }, RECENT_EVENT_WINDOW_MS + 50)
        return () => clearTimeout(t)
    }, [focus.target, focus.tick])

    // Banner only makes sense in concierge mode — in playground the dock
    // isn't navigating, it's chatting *with* an agent.
    if (context.mode !== 'concierge') {
        return null
    }

    const isOn = focus.enabled
    const isRecent = isOn && recent !== null && Date.now() - recent.at < RECENT_EVENT_WINDOW_MS
    const description = isOn
        ? (describe(focus.target) ?? 'the dock will navigate to whatever it works on')
        : 'the dock will narrate but won’t navigate'

    return (
        <div
            data-slot="focus-mode-banner"
            data-enabled={isOn || undefined}
            data-recent={isRecent || undefined}
            className={
                'sticky top-0 z-20 flex h-7 items-center gap-2 border-b px-4 text-[0.6875rem] transition-colors ' +
                (isRecent
                    ? 'border-info/40 bg-info/15 text-info-foreground'
                    : isOn
                      ? 'border-info/20 bg-info/5 text-info-foreground'
                      : 'border-border/60 bg-background text-muted-foreground')
            }
            role="status"
            aria-live="polite"
        >
            {isOn ? (
                <EyeIcon className={'h-3 w-3 shrink-0 ' + (isRecent ? '' : 'text-info-foreground/80')} />
            ) : (
                <EyeOffIcon className="h-3 w-3 shrink-0 text-muted-foreground/70" />
            )}
            <span className="font-medium">{isOn ? 'Focus mode on' : 'Focus mode off'}</span>
            <span className="hidden truncate text-muted-foreground sm:inline">· {description}</span>
            <button
                type="button"
                onClick={() => focus.setEnabled(!isOn)}
                className={
                    (isOn
                        ? 'text-info-foreground hover:bg-info/20'
                        : 'text-muted-foreground hover:bg-accent hover:text-foreground') +
                    ' ml-auto cursor-pointer rounded px-1.5 py-0.5 text-[0.6875rem] font-medium transition-colors'
                }
                aria-label={isOn ? 'Pause focus mode' : 'Resume focus mode'}
            >
                {isOn ? 'Pause' : 'Resume'}
            </button>
        </div>
    )
}

function describe(target: FocusTarget | null): string | null {
    if (!target) {
        return null
    }
    switch (target.kind) {
        case 'tab':
            return `viewing the ${target.tab} tab`
        case 'file':
            return `opened ${target.path}`
        case 'revision':
            return `viewing revision ${target.revisionId.split('-').at(-1)?.slice(0, 8) ?? target.revisionId}`
        case 'session':
            return `viewing session ${target.sessionId.split('-').at(-1)?.slice(0, 8) ?? target.sessionId}`
        case 'spec_section':
            return `viewing the ${target.section} section`
        default:
            return null
    }
}
