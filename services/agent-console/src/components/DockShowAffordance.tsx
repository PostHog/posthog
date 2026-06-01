/**
 * `<DockShowAffordance />` — the "summon the dock" affordance shown
 * when the chat is hidden. Positioned to match wherever the user
 * last had the dock:
 *
 *   - **Rail mode** → top-right tab, hugging the right edge.
 *   - **Floating, snapped left/right** → vertical tab on that edge.
 *   - **Floating, snapped to a corner** → small tab in the same corner.
 *   - **Floating, free-floating** → a pill anchored at the panel's
 *     saved position so the chat "comes back" where it was.
 *
 * Visual flair: the tab has a primary-tinted background + subtle
 * shadow + a quiet pulse on the chat icon, so it's discoverable
 * without being noisy. Hover lifts the colour. Shortcut hint
 * (`⌘.` / `Ctrl+.`) is shown beside the icon when there's room and
 * always available in the tooltip.
 */

'use client'

import { MessageCircleIcon } from 'lucide-react'

import type { DockLayout } from '@/lib/useDockLayout'

interface DockShowAffordanceProps {
    layout: DockLayout
    onShow: () => void
    /** Display string for the shortcut (e.g. `⌘.` or `Ctrl+.`). */
    shortcutHint: string
}

/** Distance from the viewport edge — matches `FLOAT_MARGIN` in the floating panel. */
const EDGE_GAP = 16

export function DockShowAffordance({ layout, onShow, shortcutHint }: DockShowAffordanceProps): React.ReactElement {
    const label = `Show chat (${shortcutHint})`
    const tab = pickTabStyle(layout)

    return (
        <button
            type="button"
            onClick={onShow}
            aria-label={label}
            title={label}
            data-slot="dock-show-affordance"
            className={
                'group fixed z-40 flex cursor-pointer items-center justify-center gap-1.5 border border-border bg-primary/95 text-primary-foreground shadow-lg transition-all hover:bg-primary hover:shadow-xl ' +
                tab.className
            }
            style={tab.style}
        >
            <MessageCircleIcon className="h-4 w-4 group-hover:animate-pulse" />
            {tab.showHint ? <span className="font-mono text-[0.625rem] opacity-80">{shortcutHint}</span> : null}
        </button>
    )
}

interface TabStyle {
    className: string
    style: React.CSSProperties
    /** Whether to show the inline shortcut hint (suppressed for tiny tabs). */
    showHint: boolean
}

/**
 * Pick the position + shape of the show-tab from the layout state.
 * Vertical edge snaps get a tall tab on that edge; corners get a
 * smaller tab in the same corner; free-floating + rail anchor on the
 * right side so the affordance is consistently findable.
 */
function pickTabStyle(layout: DockLayout): TabStyle {
    if (layout.mode === 'floating') {
        switch (layout.floating.snap) {
            case 'left':
                return {
                    className: 'rounded-r-md',
                    style: { left: 0, top: '50%', transform: 'translateY(-50%)', height: 96, width: 28 },
                    showHint: false,
                }
            case 'right':
                return {
                    className: 'rounded-l-md',
                    style: { right: 0, top: '50%', transform: 'translateY(-50%)', height: 96, width: 28 },
                    showHint: false,
                }
            case 'top-left':
                return {
                    className: 'rounded-br-md',
                    style: { left: 0, top: 0, height: 36, paddingInline: 12 },
                    showHint: true,
                }
            case 'top-right':
                return {
                    className: 'rounded-bl-md',
                    style: { right: 0, top: 0, height: 36, paddingInline: 12 },
                    showHint: true,
                }
            case 'bottom-left':
                return {
                    className: 'rounded-tr-md',
                    style: { left: 0, bottom: 0, height: 36, paddingInline: 12 },
                    showHint: true,
                }
            case 'bottom-right':
                return {
                    className: 'rounded-tl-md',
                    style: { right: 0, bottom: 0, height: 36, paddingInline: 12 },
                    showHint: true,
                }
            case null:
            default:
                // Free-floating: anchor a pill where the panel was last seen.
                return {
                    className: 'rounded-full',
                    style: {
                        left: clampViewport(layout.floating.x, 28, 'horizontal'),
                        top: clampViewport(layout.floating.y, 28, 'vertical'),
                        height: 36,
                        paddingInline: 14,
                    },
                    showHint: true,
                }
        }
    }
    // Rail mode → right edge, top-ish so it's findable but doesn't
    // collide with whatever the page renders at the very top.
    return {
        className: 'rounded-l-md',
        style: { right: 0, top: EDGE_GAP + 24, height: 96, width: 28 },
        showHint: false,
    }
}

function clampViewport(value: number, size: number, axis: 'horizontal' | 'vertical'): number {
    if (typeof window === 'undefined') {
        return value
    }
    const extent = axis === 'horizontal' ? window.innerWidth : window.innerHeight
    return Math.max(EDGE_GAP, Math.min(value, extent - size - EDGE_GAP))
}
