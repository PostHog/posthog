import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { QueuedMessageList } from '../QueuedMessageList'
import { Composer } from './Composer'

// The Composer primitives are logic-free and controlled, so the stories own the value/submit state and
// assemble the parts the same way a real surface (the tasks run viewer, PostHog AI) does.
interface ComposerStoryArgs {
    initialValue: string
    placeholder: string
    loading: boolean
    disabled: boolean
    disabledReason?: string
    isSticky: boolean
    isThreadVisible: boolean
    submitShortcut: 'enter' | 'cmd-enter'
}

type Story = StoryObj<ComposerStoryArgs>

const meta: Meta<ComposerStoryArgs> = {
    title: 'Products/PostHog AI/Composer',
    tags: ['autodocs'],
    args: {
        initialValue: '',
        placeholder: 'Ask anything…',
        loading: false,
        disabled: false,
        disabledReason: undefined,
        isSticky: false,
        isThreadVisible: false,
        submitShortcut: 'enter',
    },
    argTypes: {
        submitShortcut: { control: 'radio', options: ['enter', 'cmd-enter'] },
    },
    render: ({ initialValue, placeholder, submitShortcut, ...rootProps }) => {
        const [value, setValue] = useState(initialValue)
        return (
            <div className="max-w-180 mx-auto p-4">
                <Composer.Root value={value} onChange={setValue} onSubmit={() => setValue('')} {...rootProps}>
                    <Composer.Frame>
                        <Composer.Field>
                            <Composer.Placeholder>{placeholder}</Composer.Placeholder>
                            <Composer.Textarea submitShortcut={submitShortcut} />
                        </Composer.Field>
                    </Composer.Frame>
                    <Composer.Submit />
                </Composer.Root>
            </div>
        )
    },
}
export default meta

/** Empty input — the overlaid placeholder shows and the send button is blocked. */
export const Default: Story = {}

/** Non-empty input — the placeholder hides and the send button is enabled. */
export const Filled: Story = {
    args: { initialValue: 'Show me weekly active users for the last 90 days' },
}

/** Mid-send: the button spins and submission is blocked. */
export const Loading: Story = {
    args: { initialValue: 'Send this follow-up', loading: true },
    // The send button spins indefinitely while loading, which the snapshot runner waits forever to settle.
    tags: ['test-skip'],
}

/** A caller-supplied reason disables the input beyond the built-in empty/loading gating. */
export const Disabled: Story = {
    args: { disabled: true, disabledReason: 'Connect a data source first' },
}

/** Follow-up variant: tighter frame radius/border and a nudged send button (`isThreadVisible`). */
export const FollowUp: Story = {
    args: { initialValue: 'One more thing…', isThreadVisible: true, submitShortcut: 'cmd-enter' },
}

/** Page-level sticky chrome: bordered, blurred, bottom-pinned container around the frame. */
export const Sticky: Story = {
    args: { isSticky: true },
    decorators: [
        (StoryFn) => (
            <div className="h-96 overflow-y-auto bg-bg-light flex flex-col justify-end">
                <StoryFn />
            </div>
        ),
    ],
}

/** With a footer row for context chips / actions inside the frame. */
export const WithFooter: Story = {
    render: ({ initialValue, placeholder, submitShortcut, ...rootProps }) => {
        const [value, setValue] = useState(initialValue)
        return (
            <div className="max-w-180 mx-auto p-4">
                <Composer.Root value={value} onChange={setValue} onSubmit={() => setValue('')} {...rootProps}>
                    <Composer.Frame>
                        <Composer.Field>
                            <Composer.Placeholder>{placeholder}</Composer.Placeholder>
                            <Composer.Textarea submitShortcut={submitShortcut} />
                        </Composer.Field>
                        <Composer.Footer>
                            <div className="flex items-center gap-1 pl-2">
                                <LemonTag type="muted">@ Current dashboard</LemonTag>
                                <LemonButton size="xsmall" type="tertiary" icon={<IconGear />} tooltip="Settings" />
                            </div>
                        </Composer.Footer>
                    </Composer.Frame>
                    <Composer.Submit />
                </Composer.Root>
            </div>
        )
    },
}

/** Editable "Up next" queue rendered in the Banner slot above the frame (the tasks follow-up surface). */
export const WithUpNextQueue: Story = {
    args: { isThreadVisible: true, submitShortcut: 'cmd-enter' },
    render: ({ initialValue, placeholder, submitShortcut, ...rootProps }) => {
        const [value, setValue] = useState(initialValue)
        const [queue, setQueue] = useState([
            { id: '1', content: 'Also break it down by browser' },
            { id: '2', content: 'And add a comparison to the previous period' },
        ])
        return (
            <div className="max-w-180 mx-auto p-4">
                <Composer.Root value={value} onChange={setValue} onSubmit={() => setValue('')} {...rootProps}>
                    <Composer.Banner>
                        <QueuedMessageList
                            messages={queue}
                            onUpdate={(id, content) =>
                                setQueue((q) => q.map((m) => (m.id === id ? { ...m, content } : m)))
                            }
                            onRemove={(id) => setQueue((q) => q.filter((m) => m.id !== id))}
                        />
                    </Composer.Banner>
                    <Composer.Frame>
                        <Composer.Field>
                            <Composer.Placeholder>{placeholder}</Composer.Placeholder>
                            <Composer.Textarea submitShortcut={submitShortcut} />
                        </Composer.Field>
                    </Composer.Frame>
                    <Composer.Submit />
                </Composer.Root>
            </div>
        )
    },
}
