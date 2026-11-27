import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonSearchableSelect } from '@posthog/lemon-ui'

import { SlackReactionEmoji } from './SlackReactionEmoji'
import { PickerEmoji, slackReactionEmojiLogic } from './slackReactionEmojiLogic'

// A menu of every standard emoji renders about 1,900 buttons, so the menu shows the first matches only.
const MAX_OPTIONS = 100

function matches(emojis: PickerEmoji[], searchTerm: string): PickerEmoji[] {
    const term = searchTerm.trim().replace(/:/g, '').toLowerCase()
    if (!term) {
        return emojis.slice(0, MAX_OPTIONS)
    }
    const startsWith = emojis.filter((emoji) => emoji.name.startsWith(term))
    const contains = emojis.filter((emoji) => !emoji.name.startsWith(term) && emoji.name.includes(term))
    return [...startsWith, ...contains].slice(0, MAX_OPTIONS)
}

/** A searchable dropdown of Slack's standard emoji and the workspace's custom emoji. The value is the emoji name. */
export function SlackEmojiSelect({
    integrationId,
    value,
    onChange,
    disabledReason,
    dataAttr,
}: {
    integrationId: number
    value: string
    onChange: (name: string) => void
    disabledReason?: string
    dataAttr: string
}): JSX.Element {
    const { pickerEmoji, emojiByName, catalogLoading, standardEmojiLoading } = useValues(
        slackReactionEmojiLogic({ integrationId })
    )
    const [searchTerm, setSearchTerm] = useState('')
    const loading = catalogLoading || standardEmojiLoading

    const options = useMemo(() => {
        const shown = matches(pickerEmoji, searchTerm)
        // The trigger shows the selected option, so it stays in the list even when the search hides it.
        if (!shown.some((emoji) => emoji.name === value)) {
            shown.unshift(emojiByName[value] ?? { name: value, character: null, imageUrl: null, custom: false })
        }
        return shown.map((emoji) => ({
            value: emoji.name,
            label: `:${emoji.name}:`,
            icon: <SlackReactionEmoji name={emoji.name} emoji={emoji} />,
        }))
    }, [pickerEmoji, emojiByName, searchTerm, value])

    return (
        <LemonSearchableSelect
            size="small"
            value={value}
            onChange={(name) => name && onChange(name)}
            options={options}
            filterOptionsLocally={false}
            onSearchChange={setSearchTerm}
            loading={loading}
            searchPlaceholder="Search emoji"
            noResultsMessage={loading ? 'Loading emoji...' : 'No emoji matches'}
            disabledReason={disabledReason}
            searchInputDataAttr={`${dataAttr}-search`}
            menu={{ className: '!max-h-80' }}
            data-attr={dataAttr}
        />
    )
}
