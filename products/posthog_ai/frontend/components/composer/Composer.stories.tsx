import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { APP_COMMANDS, buildSlashCommands } from '../../utils/slashCommands'
import { QueuedMessageList } from '../QueuedMessageList'
import { CommandResultCard } from './CommandResultCard'
import { Composer } from './Composer'
import { ComposerCommandMenu } from './ComposerCommandMenu'

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
    },
    render: ({ initialValue, placeholder, ...rootProps }) => {
        const [value, setValue] = useState(initialValue)
        return (
            <div className="w-180 mx-auto p-4">
                <Composer.Root value={value} onChange={setValue} onSubmit={() => setValue('')} {...rootProps}>
                    <Composer.Frame>
                        <Composer.Field>
                            <Composer.Placeholder>{placeholder}</Composer.Placeholder>
                            <Composer.Textarea />
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
    args: { initialValue: 'One more thing…', isThreadVisible: true },
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

/** Real-surface composition: context chips in the Header row at the top of the frame, actions in the Footer. */
export const WithHeaderAndFooter: Story = {
    render: ({ initialValue, placeholder, ...rootProps }) => {
        const [value, setValue] = useState(initialValue)
        return (
            <div className="w-180 mx-auto p-4">
                <Composer.Root value={value} onChange={setValue} onSubmit={() => setValue('')} {...rootProps}>
                    <Composer.Frame>
                        <Composer.Header className="flex flex-wrap items-center gap-1">
                            <LemonTag type="muted">@ Current dashboard</LemonTag>
                            <LemonTag type="muted">@ Weekly signups</LemonTag>
                        </Composer.Header>
                        <Composer.Field>
                            <Composer.Placeholder>{placeholder}</Composer.Placeholder>
                            <Composer.Textarea />
                        </Composer.Field>
                        <Composer.Footer>
                            <div className="flex items-center gap-1 pl-2">
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
    args: { isThreadVisible: true },
    render: ({ initialValue, placeholder, ...rootProps }) => {
        const [value, setValue] = useState(initialValue)
        const [queue, setQueue] = useState([
            { id: '1', content: 'Also break it down by browser' },
            { id: '2', content: 'And add a comparison to the previous period' },
        ])
        return (
            <div className="w-180 mx-auto p-4">
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
                            <Composer.Textarea />
                        </Composer.Field>
                    </Composer.Frame>
                    <Composer.Submit />
                </Composer.Root>
            </div>
        )
    },
}

const STORY_SLASH_COMMANDS = buildSlashCommands(APP_COMMANDS, [
    { name: 'clear', description: 'Clear conversation history and free up context' },
    { name: 'compact', description: 'Clear conversation history but keep a summary in context' },
    // Kept verbose: the menu's width cap is only exercised by a description this long.
    {
        name: 'querying-posthog-data',
        description:
            'Required reading before writing any HogQL/SQL or calling execute-sql against PostHog. Use whenever the user wants to search, find, or do complex aggregations over PostHog entities and query analytics data.',
        hint: 'question',
    },
])

/** Typing `/` opens the slash command menu, and a side question answer sits in the Banner slot. */
export const WithSlashCommands: Story = {
    args: { initialValue: '/', isThreadVisible: true },
    render: ({ initialValue, placeholder, ...rootProps }) => {
        const [value, setValue] = useState(initialValue)
        const [showResult, setShowResult] = useState(true)
        return (
            <div className="w-180 mx-auto p-4 pt-96">
                <Composer.Root value={value} onChange={setValue} onSubmit={() => setValue('')} {...rootProps}>
                    {showResult && (
                        <Composer.Banner>
                            <CommandResultCard
                                title="Which table holds the signup events?"
                                body="Signups are `user signed up` events in the `events` table."
                                onDismiss={() => setShowResult(false)}
                            />
                        </Composer.Banner>
                    )}
                    <Composer.Frame>
                        <ComposerCommandMenu commands={STORY_SLASH_COMMANDS}>
                            <Composer.Field>
                                <Composer.Placeholder>{placeholder}</Composer.Placeholder>
                                <Composer.Textarea />
                            </Composer.Field>
                        </ComposerCommandMenu>
                    </Composer.Frame>
                    <Composer.Submit />
                </Composer.Root>
            </div>
        )
    },
}

/** Before the agent has advertised its own commands, the menu says so rather than looking complete. */
export const WithAppSlashCommandsOnly: Story = {
    args: { initialValue: '/', isThreadVisible: true },
    render: ({ initialValue, placeholder, ...rootProps }) => {
        const [value, setValue] = useState(initialValue)
        return (
            <div className="w-180 mx-auto p-4 pt-96">
                <Composer.Root value={value} onChange={setValue} onSubmit={() => setValue('')} {...rootProps}>
                    <Composer.Frame>
                        <ComposerCommandMenu commands={buildSlashCommands(APP_COMMANDS, [])}>
                            <Composer.Field>
                                <Composer.Placeholder>{placeholder}</Composer.Placeholder>
                                <Composer.Textarea />
                            </Composer.Field>
                        </ComposerCommandMenu>
                    </Composer.Frame>
                    <Composer.Submit />
                </Composer.Root>
            </div>
        )
    },
}
