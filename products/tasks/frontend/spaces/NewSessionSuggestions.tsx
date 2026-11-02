import { useState } from 'react'

import { IconBug, IconCode, IconMessage, IconPalette, IconPiggyBank, IconTrending } from '@posthog/icons'
import {
    IconStack,
    IconStackItem,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Text,
} from '@posthog/quill'

import type { NewSessionSuggestion, NewSessionSuggestionIcon } from './newSessionSuggestionDefaults'

const SUGGESTION_ICONS: Record<NewSessionSuggestionIcon, { Icon: typeof IconBug; color: string }> = {
    trends: { Icon: IconTrending, color: 'var(--color-product-customer-analytics-light)' },
    bug: { Icon: IconBug, color: 'var(--color-product-error-tracking-light)' },
    canvas: { Icon: IconPalette, color: 'var(--color-product-product-analytics-light)' },
    code: { Icon: IconCode, color: 'var(--color-product-tasks-light)' },
    revenue: { Icon: IconPiggyBank, color: 'var(--color-product-revenue-analytics-light)' },
    feedback: { Icon: IconMessage, color: 'var(--color-product-llm-analytics-light)' },
}

export interface NewSessionSuggestionsProps {
    suggestions: NewSessionSuggestion[]
    onSelect: (suggestion: NewSessionSuggestion, index: number) => void
}

export function NewSessionSuggestions({ suggestions, onSelect }: NewSessionSuggestionsProps): JSX.Element {
    const [activeId, setActiveId] = useState<string | null>(null)

    return (
        <div className="@container/new-session-suggestions flex flex-col gap-2">
            <Text size="xs" variant="muted" weight="medium" className="px-1">
                Suggestions
            </Text>
            <div className="grid grid-cols-1 gap-2 @lg/new-session-suggestions:grid-cols-2">
                {suggestions.map((suggestion, index) => {
                    const { Icon, color } = SUGGESTION_ICONS[suggestion.icon]
                    const activate = (): void => setActiveId(suggestion.id)
                    const deactivate = (): void => setActiveId(null)
                    return (
                        <Item
                            key={suggestion.id}
                            variant="outline"
                            size="sm"
                            className="cursor-pointer items-start bg-card text-left text-card-foreground hover:bg-fill-hover"
                            render={
                                <button
                                    type="button"
                                    onClick={() => onSelect(suggestion, index)}
                                    onMouseEnter={activate}
                                    onMouseLeave={deactivate}
                                    onFocus={activate}
                                    onBlur={deactivate}
                                    data-attr="today-new-session-suggestion"
                                />
                            }
                        >
                            <ItemMedia>
                                <IconStack className="[--quill-icon-stack-ring:transparent]">
                                    <IconStackItem
                                        color={color}
                                        active={activeId === suggestion.id}
                                        className="bg-clip-padding"
                                    >
                                        <Icon />
                                    </IconStackItem>
                                </IconStack>
                            </ItemMedia>
                            <ItemContent className="min-w-0">
                                <ItemTitle className="w-full truncate">{suggestion.label}</ItemTitle>
                                <ItemDescription>{suggestion.description}</ItemDescription>
                            </ItemContent>
                        </Item>
                    )
                })}
            </div>
        </div>
    )
}
