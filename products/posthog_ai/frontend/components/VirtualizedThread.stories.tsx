import type { Meta, StoryObj } from '@storybook/react'
import { useEffect, useRef, useState } from 'react'

import { cn } from 'lib/utils/css-classes'
import { inStorybookTestRunner } from 'lib/utils/dom'

import { VirtualizedThread } from './VirtualizedThread'

// Standalone, logic-free harness for the virtualized thread presenter — no `runStreamLogic`, no real
// `ThreadRow`. Fixtures are deterministic fake messages of varying height, exactly the shape that regressed
// twice (open-at-bottom flicker + the streaming stick-to-bottom crash). Each row is wrapped in
// `VirtualizedThread.Row` like the real consumer does.
const meta: Meta = {
    title: 'Products/PostHog AI/VirtualizedThread',
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj

interface FakeItem {
    id: string
    role: 'user' | 'assistant'
    text: string
}

const LOREM =
    'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore ' +
    'et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut ' +
    'aliquip ex ea commodo consequat.'

/** Deterministic variable-height content — every 3rd row is long, so rows measure to different heights. */
function makeItems(count: number): FakeItem[] {
    return Array.from({ length: count }, (_, i) => ({
        id: `item-${i}`,
        role: i % 2 === 0 ? 'assistant' : 'user',
        text: i % 3 === 0 ? `#${i} — ${LOREM} ${LOREM}` : `#${i} — ${LOREM.slice(0, 60)}`,
    }))
}

function FakeMessage({ role, text }: { role: FakeItem['role']; text: string }): JSX.Element {
    return (
        <div className={cn('rounded border p-3 bg-surface-primary', role === 'user' && 'ml-8')}>
            <div className="text-xs text-muted mb-1">{role}</div>
            <div className="text-sm">{text}</div>
        </div>
    )
}

const getKey = (item: FakeItem): string => item.id

// Story wrappers use a fixed `w-180` (720px, the thread's own max row width) instead of `w-full`: in the
// visual-regression runtime `#storybook-root` is `inline-block` (it hugs the component), and the virtualized
// rows are absolutely positioned — no intrinsic width — so a percentage width collapses the snapshot to the
// wrapper's 2px border.

/** Long static thread — opens already scrolled to the last message, with no top-frame flicker or crawl. */
export const LongThread: Story = {
    render: () => {
        const items = makeItems(80)
        return (
            <div className="h-[600px] w-180 border rounded overflow-hidden">
                <VirtualizedThread.Root items={items} getItemKey={getKey} stickToBottom>
                    {(item) => (
                        <VirtualizedThread.Row>
                            <FakeMessage role={item.role} text={item.text} />
                        </VirtualizedThread.Row>
                    )}
                </VirtualizedThread.Root>
            </div>
        )
    },
}

/** Bounded embed (mirrors the inbox `h-[420px] overflow-hidden` detail panel) — the Root owns the only scroll. */
export const BoundedEmbed: Story = {
    render: () => {
        const items = makeItems(40)
        return (
            <div className="h-[420px] w-180 mx-auto border rounded overflow-hidden">
                <VirtualizedThread.Root
                    items={items}
                    getItemKey={getKey}
                    header={
                        <VirtualizedThread.Row>
                            <div className="text-xs text-muted p-2">Run context header</div>
                        </VirtualizedThread.Row>
                    }
                    stickToBottom
                >
                    {(item) => (
                        <VirtualizedThread.Row>
                            <FakeMessage role={item.role} text={item.text} />
                        </VirtualizedThread.Row>
                    )}
                </VirtualizedThread.Root>
            </div>
        )
    },
}

/**
 * Streaming, static snapshot — the same mid-stream state as `StreamingDebug` (a few settled messages, a
 * partially streamed tail, `turnActive`) frozen at a fixed tick, so the visual-regression run captures the
 * bottom-pinned streaming posture without timers.
 */
export const Streaming: Story = {
    render: () => {
        const items = [
            ...makeItems(6),
            { id: 'stream-4', role: 'assistant' as const, text: '#6 — streamed message' },
            { id: 'stream-8', role: 'assistant' as const, text: '#7 — streamed message' },
        ]
        return (
            <div className="h-[600px] w-180 border rounded overflow-hidden">
                <VirtualizedThread.Root
                    items={items}
                    getItemKey={getKey}
                    footer={
                        <VirtualizedThread.Row>
                            <div className="rounded border p-3 bg-surface-primary text-sm text-muted">
                                Thinking {LOREM.slice(0, 40)}…
                            </div>
                        </VirtualizedThread.Row>
                    }
                    stickToBottom
                    turnActive
                >
                    {(item) => (
                        <VirtualizedThread.Row>
                            <FakeMessage role={item.role} text={item.text} />
                        </VirtualizedThread.Row>
                    )}
                </VirtualizedThread.Root>
            </div>
        )
    },
}

/**
 * Streaming, live timers — appends items and grows the height of the last message; the viewport stays pinned
 * to the bottom (`turnActive` simulates the agent working, which is what gates append-following). This
 * exercises the height-only-growth stick path. Debugging only: timers make it non-deterministic, so it is
 * excluded from the visual-regression run (`test-skip`) — capture `Streaming` instead.
 */
export const StreamingDebug: Story = {
    tags: ['test-skip'],
    render: () => {
        const [items, setItems] = useState<FakeItem[]>(() => makeItems(6))
        const [tail, setTail] = useState('Thinking')
        const tickRef = useRef(0)

        useEffect(() => {
            if (inStorybookTestRunner()) {
                return
            }
            const interval = setInterval(() => {
                tickRef.current += 1
                const tick = tickRef.current
                // Alternate between growing the last message (token stream) and appending a new one.
                if (tick % 4 === 0) {
                    setItems((prev) => [
                        ...prev,
                        { id: `stream-${tick}`, role: 'assistant', text: `#${prev.length} — streamed message` },
                    ])
                    setTail('Thinking')
                } else {
                    setTail((prev) => `${prev} ${LOREM.slice(0, 40)}`)
                }
            }, 700)
            return () => clearInterval(interval)
        }, [])

        return (
            <div className="h-[600px] w-180 border rounded overflow-hidden">
                <VirtualizedThread.Root
                    items={items}
                    getItemKey={getKey}
                    footer={
                        <VirtualizedThread.Row>
                            <div className="rounded border p-3 bg-surface-primary text-sm text-muted">{tail}…</div>
                        </VirtualizedThread.Row>
                    }
                    stickToBottom
                    turnActive
                >
                    {(item) => (
                        <VirtualizedThread.Row>
                            <FakeMessage role={item.role} text={item.text} />
                        </VirtualizedThread.Row>
                    )}
                </VirtualizedThread.Root>
            </div>
        )
    },
}

/** Empty thread (rowCount 0) — renders an empty scroll container, no rows, stick effects no-op. */
export const Empty: Story = {
    render: () => (
        <div className="h-[300px] w-180 border rounded overflow-hidden">
            <VirtualizedThread.Root items={[] as FakeItem[]} getItemKey={getKey} stickToBottom>
                {(item) => (
                    <VirtualizedThread.Row>
                        <FakeMessage role={item.role} text={item.text} />
                    </VirtualizedThread.Row>
                )}
            </VirtualizedThread.Root>
        </div>
    ),
}

/** Header + footer only (no items) — the offset mapping still resolves both synthetic rows. */
export const HeaderFooterOnly: Story = {
    render: () => (
        <div className="h-[300px] w-180 border rounded overflow-hidden">
            <VirtualizedThread.Root
                items={[] as FakeItem[]}
                getItemKey={getKey}
                header={
                    <VirtualizedThread.Row>
                        <div className="text-xs text-muted p-2">Run context header</div>
                    </VirtualizedThread.Row>
                }
                footer={
                    <VirtualizedThread.Row>
                        <div className="rounded border p-3 bg-surface-primary text-sm text-muted">Thinking…</div>
                    </VirtualizedThread.Row>
                }
                stickToBottom
            >
                {(item) => (
                    <VirtualizedThread.Row>
                        <FakeMessage role={item.role} text={item.text} />
                    </VirtualizedThread.Row>
                )}
            </VirtualizedThread.Root>
        </div>
    ),
}

/**
 * Anchored open — mirrors reopening a saved conversation: the thread mounts with all items already present
 * and `anchorItemKey` pointing at the last "user" message, which has more than a viewport of content after
 * it. Must land with the anchor at the top of the viewport, not at the bottom. The height estimate is a
 * deliberate undershoot (46px vs ~200px real), the same skew the real `THREAD_ITEM_HEIGHT_ESTIMATES` has.
 * The 400px wrapper is intentionally shorter than the canvas so the bounded container — and where the
 * scroll landed inside it — is visible in the snapshot.
 */
export const AnchoredOpen: Story = {
    render: () => {
        // 30 items; the anchor "user" message is #21, followed by 8 long rows (several viewports of tail).
        const items = makeItems(30).map((item, i) => {
            if (i === 21) {
                return {
                    ...item,
                    role: 'user' as const,
                    text: `#${i} (user, the anchor) — EXPECTED ON OPEN: this message sits at the TOP of the viewport, because more than a viewport of response follows it.`,
                }
            }
            if (i > 21) {
                return {
                    ...item,
                    role: 'assistant' as const,
                    text:
                        i === 29
                            ? `#${i} — EXPECTED: the end of the thread stays below the fold, reached by scrolling down. ${LOREM}`
                            : `#${i} — response under the anchor; visible below it or below the fold. ${LOREM} ${LOREM}`,
                }
            }
            return item
        })
        return (
            <div className="h-[400px] w-180 border rounded overflow-hidden">
                <VirtualizedThread.Root
                    items={items}
                    getItemKey={getKey}
                    estimateItemHeight={() => 46}
                    anchorItemKey="item-21"
                    stickToBottom
                >
                    {(item) => (
                        <VirtualizedThread.Row>
                            <FakeMessage role={item.role} text={item.text} />
                        </VirtualizedThread.Row>
                    )}
                </VirtualizedThread.Root>
            </div>
        )
    },
}

/**
 * Anchored open, mid-turn with a short tail — reopening a thread the agent is still working on, with less
 * than a viewport of response under the anchor. The top is unreachable, so this must open at the bottom,
 * pinned (no padding is reserved to force the anchor higher). Static (`turnActive` but no timers), so the
 * visual-regression run captures the clamped landing without flakes. The 400px wrapper keeps the bounded
 * container visible in the snapshot.
 */
export const AnchoredOpenMidTurn: Story = {
    render: () => {
        const items = makeItems(30).map((item, i) => {
            if (i === 27) {
                return {
                    ...item,
                    role: 'user' as const,
                    text: `#${i} (user, the anchor) — EXPECTED ON OPEN: NOT at the top. Less than a viewport of response follows, so the thread opens clamped to the BOTTOM, pinned — no whitespace is reserved to push this row higher.`,
                }
            }
            if (i > 27) {
                return {
                    ...item,
                    role: 'assistant' as const,
                    text:
                        i === 29
                            ? `#${i} — EXPECTED: this last row sits at the bottom edge of the viewport on open.`
                            : `#${i} — short response under the anchor. ${LOREM.slice(0, 80)}`,
                }
            }
            return item
        })
        return (
            <div className="h-[400px] w-180 border rounded overflow-hidden">
                <VirtualizedThread.Root
                    items={items}
                    getItemKey={getKey}
                    estimateItemHeight={() => 46}
                    anchorItemKey="item-27"
                    stickToBottom
                    turnActive
                >
                    {(item) => (
                        <VirtualizedThread.Row>
                            <FakeMessage role={item.role} text={item.text} />
                        </VirtualizedThread.Row>
                    )}
                </VirtualizedThread.Root>
            </div>
        )
    },
}

/**
 * Anchored open, mid-turn, live timers — the same short-tail open as `AnchoredOpenMidTurn`, but a timer
 * keeps appending streamed rows: the thread opens at the bottom, pinned, and follows the appends.
 * Debugging only: excluded from the visual-regression run (`test-skip`) — capture `AnchoredOpenMidTurn`
 * instead.
 */
export const AnchoredOpenMidTurnDebug: Story = {
    tags: ['test-skip'],
    render: () => {
        const [items, setItems] = useState<FakeItem[]>(() =>
            makeItems(30).map((item, i) => (i >= 27 ? { ...item, text: `#${i} — ${LOREM} ${LOREM}` } : item))
        )
        useEffect(() => {
            if (inStorybookTestRunner()) {
                return
            }
            const interval = setInterval(() => {
                setItems((prev) => [
                    ...prev,
                    { id: `stream-${prev.length}`, role: 'assistant', text: `#${prev.length} — streamed` },
                ])
            }, 700)
            return () => clearInterval(interval)
        }, [])
        return (
            <div className="h-[600px] w-180 border rounded overflow-hidden">
                <VirtualizedThread.Root
                    items={items}
                    getItemKey={getKey}
                    estimateItemHeight={() => 46}
                    anchorItemKey="item-27"
                    stickToBottom
                    turnActive
                >
                    {(item) => (
                        <VirtualizedThread.Row>
                            <FakeMessage role={item.role} text={item.text} />
                        </VirtualizedThread.Row>
                    )}
                </VirtualizedThread.Root>
            </div>
        )
    },
}

/**
 * Anchored open, mid-turn with a long tail — reopening a thread the agent is still working on, with more
 * than a viewport of response already under the anchor. This is a reading position: the anchor must land at
 * the top of the viewport and stay there — streaming below must not steal the view. Static and
 * deterministic, so the visual-regression run captures it. The 400px wrapper keeps the bounded container
 * visible in the snapshot.
 */
export const AnchoredOpenMidTurnLongTail: Story = {
    render: () => {
        const items = makeItems(30).map((item, i) => {
            if (i === 21) {
                return {
                    ...item,
                    role: 'user' as const,
                    text: `#${i} (user, the anchor) — EXPECTED ON OPEN (mid-turn): at the TOP of the viewport, and it STAYS there — the stream growing below must not steal this reading position.`,
                }
            }
            if (i > 21) {
                return {
                    ...item,
                    role: 'assistant' as const,
                    text: `#${i} — in-progress response under the anchor; the tail already exceeds a viewport. ${LOREM} ${LOREM}`,
                }
            }
            return item
        })
        return (
            <div className="h-[400px] w-180 border rounded overflow-hidden">
                <VirtualizedThread.Root
                    items={items}
                    getItemKey={getKey}
                    estimateItemHeight={() => 46}
                    anchorItemKey="item-21"
                    stickToBottom
                    turnActive
                >
                    {(item) => (
                        <VirtualizedThread.Row>
                            <FakeMessage role={item.role} text={item.text} />
                        </VirtualizedThread.Row>
                    )}
                </VirtualizedThread.Root>
            </div>
        )
    },
}

/**
 * Deferred open — simulates the history replay: the thread mounts with a few rows and `itemsLoading`,
 * more rows fold in over two ticks, then loading clears with the full thread. The once-only opening
 * scroll must wait for the final commit and land on the anchor ("user" #21 at the top) — spending it on a
 * partial commit is the bug that opened every debug-logs-on thread at the bottom. Debugging only: the
 * phase timers make it non-deterministic for capture (`test-skip`).
 */
export const DeferredOpenDebug: Story = {
    tags: ['test-skip'],
    render: () => {
        // The tail after the anchor is all-assistant (a long response), so the dynamically derived
        // anchor — the last "user" item, like the real consumer — stays #21 across every phase.
        const full = makeItems(30).map((item, i) =>
            i >= 21
                ? {
                      ...item,
                      role: i === 21 ? ('user' as const) : ('assistant' as const),
                      text: `#${i} — ${LOREM} ${LOREM}`,
                  }
                : item
        )
        const [phase, setPhase] = useState(0)
        useEffect(() => {
            if (inStorybookTestRunner()) {
                return
            }
            const t1 = setTimeout(() => setPhase(1), 400)
            const t2 = setTimeout(() => setPhase(2), 900)
            return () => {
                clearTimeout(t1)
                clearTimeout(t2)
            }
        }, [])
        const items = phase === 0 ? full.slice(0, 3) : phase === 1 ? full.slice(0, 12) : full
        const lastUser = items.findLast((item) => item.role === 'user')
        return (
            <div className="h-[600px] w-180 border rounded overflow-hidden">
                <VirtualizedThread.Root
                    items={items}
                    getItemKey={getKey}
                    estimateItemHeight={() => 46}
                    anchorItemKey={lastUser?.id ?? null}
                    itemsLoading={phase < 2}
                    stickToBottom
                >
                    {(item) => (
                        <VirtualizedThread.Row>
                            <FakeMessage role={item.role} text={item.text} />
                        </VirtualizedThread.Row>
                    )}
                </VirtualizedThread.Root>
            </div>
        )
    },
}

/**
 * Send and anchor-jump — interactive harness for the two anchor-change behaviors. "Send" appends a new
 * "user" message and points `anchorItemKey` at it (a *novel* key = a fresh send): the thread must pin to
 * the bottom and follow the streamed response, with the sent message riding up naturally. "Jump to first
 * user message" re-points the anchor at an *existing* key (a replayed turn): the thread must scroll that
 * row to the top without pinning. Debugging only (`test-skip`): both are transitions, not landings.
 */
export const SendAndJumpDebug: Story = {
    tags: ['test-skip'],
    render: () => {
        const [items, setItems] = useState<FakeItem[]>(() => makeItems(30))
        const [anchorKey, setAnchorKey] = useState<string>('item-29')
        const [turnActive, setTurnActive] = useState(false)
        const seqRef = useRef(0)

        useEffect(() => {
            if (!turnActive || inStorybookTestRunner()) {
                return
            }
            const interval = setInterval(() => {
                setItems((prev) => [
                    ...prev,
                    { id: `stream-${prev.length}`, role: 'assistant', text: `#${prev.length} — streamed response` },
                ])
            }, 700)
            return () => clearInterval(interval)
        }, [turnActive])

        const send = (): void => {
            const id = `sent-${seqRef.current++}`
            setItems((prev) => [...prev, { id, role: 'user', text: `sent message ${id}` }])
            setAnchorKey(id)
            setTurnActive(true)
        }

        return (
            <div className="flex flex-col gap-2">
                <div className="flex gap-2">
                    <button className="border rounded px-2 py-1" onClick={send}>
                        Send
                    </button>
                    <button className="border rounded px-2 py-1" onClick={() => setAnchorKey('item-1')}>
                        Jump to first user message
                    </button>
                    <button className="border rounded px-2 py-1" onClick={() => setTurnActive(false)}>
                        End turn
                    </button>
                </div>
                <div className="h-[600px] w-180 border rounded overflow-hidden">
                    <VirtualizedThread.Root
                        items={items}
                        getItemKey={getKey}
                        anchorItemKey={anchorKey}
                        stickToBottom
                        turnActive={turnActive}
                    >
                        {(item) => (
                            <VirtualizedThread.Row>
                                <FakeMessage role={item.role} text={item.text} />
                            </VirtualizedThread.Row>
                        )}
                    </VirtualizedThread.Root>
                </div>
            </div>
        )
    },
}

/**
 * Flow mode (`virtualized={false}`) — rows render into document flow with no chrome, no scroll container, no
 * measurement. An ancestor owns scroll (here, a plain bounded div). This is the Max live-column path.
 */
export const FlowMode: Story = {
    render: () => {
        const items = makeItems(12)
        return (
            <div className="h-[500px] w-180 mx-auto overflow-y-auto border rounded flex flex-col gap-1.5 p-2">
                <VirtualizedThread.Root items={items} getItemKey={getKey} virtualized={false}>
                    {(item) => (
                        <VirtualizedThread.Row>
                            <FakeMessage role={item.role} text={item.text} />
                        </VirtualizedThread.Row>
                    )}
                </VirtualizedThread.Root>
            </div>
        )
    },
}
