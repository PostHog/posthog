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
 * Streaming — a timer appends items and grows the height of the last message; the viewport stays pinned to the
 * bottom. This exercises the height-only-growth stick path, the case `anchorTo: 'end'` does not cover. Timers
 * are non-deterministic, so this story is skipped in the visual-regression run.
 */
export const Streaming: Story = {
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
