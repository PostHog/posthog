import { useValues } from 'kea'

import {
    Autocomplete,
    AutocompleteContent,
    AutocompleteInput,
    AutocompleteItem,
    AutocompleteList,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { aiVisibilityTopicsLogic } from './aiVisibilityTopicsLogic'
import { sameTopic } from './utils'

/** A topic field that offers the project's topics as the user types, so a new spelling of a topic is a choice. */
export const AiVisibilityTopicInput = ({
    id,
    value,
    onChange,
    maxLength,
    placeholder,
    autoFocus,
    dataAttr,
}: {
    id: string
    value: string
    onChange: (topic: string) => void
    maxLength: number
    placeholder?: string
    autoFocus?: boolean
    dataAttr: string
}): JSX.Element => {
    const { namedTopics } = useValues(aiVisibilityTopicsLogic)
    const typed = value.trim()
    const isNew = typed !== '' && !namedTopics.some(({ topic }) => sameTopic(topic, typed))
    const items = [...namedTopics.map(({ topic }) => topic), ...(isNew ? [typed] : [])]
    const promptCounts = new Map(namedTopics.map(({ topic, prompts }) => [topic, prompts]))

    return (
        <Autocomplete items={items} value={value} onValueChange={(next: string) => onChange(next)}>
            <AutocompleteInput
                id={id}
                showSearchIcon={false}
                maxLength={maxLength}
                placeholder={placeholder}
                autoFocus={autoFocus}
                data-attr={dataAttr}
            />
            <AutocompleteContent>
                <AutocompleteList>
                    {(topic: string) => (
                        <AutocompleteItem key={topic} value={topic}>
                            {promptCounts.has(topic) ? (
                                <span className="flex w-full justify-between gap-4">
                                    <span>{topic}</span>
                                    <span className="text-muted-foreground">
                                        {pluralize(promptCounts.get(topic) ?? 0, 'prompt')}
                                    </span>
                                </span>
                            ) : (
                                `Create "${topic}"`
                            )}
                        </AutocompleteItem>
                    )}
                </AutocompleteList>
            </AutocompleteContent>
        </Autocomplete>
    )
}
