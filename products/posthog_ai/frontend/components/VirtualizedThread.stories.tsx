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
 */
export const AnchoredOpen: Story = {
    render: () => {
        // 30 items; the anchor "user" message is #21, followed by 8 long rows (~1200px, two viewports).
        const items = makeItems(30).map((item, i) => (i >= 21 ? { ...item, text: `#${i} — ${LOREM} ${LOREM}` } : item))
        const anchorKey = 'item-21'
        return (
            <div className="h-[600px] w-180 border rounded overflow-hidden">
                <VirtualizedThread.Root
                    items={items}
                    getItemKey={getKey}
                    estimateItemHeight={() => 46}
                    anchorItemKey={anchorKey}
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
 * than a viewport of response under the anchor so a plain scroll would clamp to the bottom. Must open with
 * the anchor at the top over reserved space (the fresh-send posture). Static (`turnActive` but no timers),
 * so the visual-regression run captures the reserve landing without flakes.
 */
export const AnchoredOpenMidTurn: Story = {
    render: () => {
        const items = makeItems(30).map((item, i) => (i >= 27 ? { ...item, text: `#${i} — ${LOREM} ${LOREM}` } : item))
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
 * Anchored open, mid-turn, live timers — the same short-tail reserve open as `AnchoredOpenMidTurn`, but a
 * timer keeps appending streamed rows: the reserve absorbs them 1:1 (view static), and once the response
 * outgrows the viewport stick-to-bottom takes over. Debugging only: excluded from the visual-regression run
 * (`test-skip`) — capture `AnchoredOpenMidTurn` instead.
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
