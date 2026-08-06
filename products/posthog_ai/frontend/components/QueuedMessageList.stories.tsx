import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { QueuedMessage } from '../logics/runInteractionLogic'
import { QueuedMessageList } from './QueuedMessageList'

// Logic-free and controlled — the story owns the queue and wires `onUpdate` / `onRemove`, exactly as the
// run surface does. Hover a row to reveal edit/remove; editing swaps the row for an inline editor.
const meta: Meta<typeof QueuedMessageList> = {
    title: 'Products/PostHog AI/QueuedMessageList',
    component: QueuedMessageList,
    tags: ['autodocs'],
    render: ({ messages }) => {
        const [queue, setQueue] = useState<QueuedMessage[]>(messages)
        return (
            <div className="max-w-180 mx-auto p-4">
                <QueuedMessageList
                    messages={queue}
                    onUpdate={(id, content) => setQueue((q) => q.map((m) => (m.id === id ? { ...m, content } : m)))}
                    onRemove={(id) => setQueue((q) => q.filter((m) => m.id !== id))}
                />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<typeof QueuedMessageList>

export const Single: Story = {
    args: { messages: [{ id: '1', content: 'Also break it down by browser' }] },
}

export const Multiple: Story = {
    args: {
        messages: [
            { id: '1', content: 'Also break it down by browser' },
            { id: '2', content: 'And add a comparison to the previous period' },
            { id: '3', content: 'Then export the result to a dashboard' },
        ],
    },
}

/** Empty queue renders nothing — the consumer hides the Banner slot entirely. */
export const Empty: Story = {
    args: { messages: [] },
}
