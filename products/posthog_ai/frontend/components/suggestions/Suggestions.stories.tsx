import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { Composer } from '../composer/Composer'
import { type SuggestionGroup, type SuggestionItem, Suggestions } from './Suggestions'
import { DEFAULT_SUGGESTIONS_DATA } from './suggestionsDefaults'

// The Suggestions primitives are logic-free and controlled: the story owns the open-dropdown state and the
// composer value, assembling the parts the way a real surface (the tasks composer) does. The dropdown
// attaches to the bottom edge of <Composer.Root>.
interface SuggestionsStoryArgs {
    initialActiveGroupIndex: number | null
}

type Story = StoryObj<SuggestionsStoryArgs>

const meta: Meta<SuggestionsStoryArgs> = {
    title: 'Products/PostHog AI/Suggestions',
    tags: ['autodocs'],
    args: { initialActiveGroupIndex: null },
    render: ({ initialActiveGroupIndex }) => {
        const [value, setValue] = useState('')
        const [activeGroup, setActiveGroup] = useState<SuggestionGroup | null>(
            initialActiveGroupIndex !== null ? DEFAULT_SUGGESTIONS_DATA[initialActiveGroupIndex] : null
        )
        const onSelectSuggestion = (item: SuggestionItem): void => {
            setValue(item.content)
            setActiveGroup(null)
        }
        return (
            <div className="max-w-2xl mx-auto p-4 flex flex-col gap-4">
                <Suggestions.Root
                    activeGroup={activeGroup}
                    onActiveGroupChange={setActiveGroup}
                    onSelectSuggestion={onSelectSuggestion}
                >
                    <Composer.Root value={value} onChange={setValue} onSubmit={() => setValue('')}>
                        <Composer.Frame>
                            <Composer.Field>
                                <Composer.Placeholder>Describe the task…</Composer.Placeholder>
                                <Composer.Textarea submitShortcut="cmd-enter" />
                            </Composer.Field>
                        </Composer.Frame>
                        <Suggestions.Dropdown />
                        <Composer.Submit />
                    </Composer.Root>
                    <Suggestions.Buttons data={DEFAULT_SUGGESTIONS_DATA} />
                </Suggestions.Root>
            </div>
        )
    },
}
export default meta

/** Collapsed — the button row under the input; clicking a multi-suggestion category opens the dropdown. */
export const Default: Story = {}

/** Expanded — a category's suggestions shown in the in-input dropdown. */
export const Expanded: Story = {
    args: { initialActiveGroupIndex: 0 },
    // The dropdown animates open via useAnimatedPresence, which the snapshot runner can catch mid-transition.
    tags: ['test-skip'],
}
