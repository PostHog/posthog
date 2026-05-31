/**
 * Two-pane layout primitive for the agent detail tabs (memory,
 * configuration, sessions). Left pane is a fixed-width browser
 * (tree / list / filter); right pane is the reader / editor that
 * fills the remaining space.
 *
 * Drop this into a tab body; both children are responsible for
 * their own internal scroll containers (the wrapper just sets
 * `overflow-hidden` on itself).
 */

'use client'

interface TwoPaneTabProps {
    left: React.ReactNode
    right: React.ReactNode
    leftWidth?: number
}

export function TwoPaneTab({ left, right, leftWidth = 320 }: TwoPaneTabProps): React.ReactElement {
    return (
        <div
            className="grid min-h-0 flex-1 divide-x divide-border overflow-hidden"
            style={{ gridTemplateColumns: `${leftWidth}px 1fr` }}
        >
            <aside className="flex flex-col overflow-hidden">{left}</aside>
            <main className="flex flex-col overflow-hidden">{right}</main>
        </div>
    )
}
