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

import { getIconColor } from '~/layout/panel-layout/ProjectTree/defaultTree'
import type { FileSystemIconType } from '~/queries/schema/schema-general'

import type { NewSessionSuggestion, NewSessionSuggestionIcon } from './newSessionSuggestionDefaults'

// Colors come from the file system type, so a suggestion matches the same object everywhere else (tree, recents, search)
const SUGGESTION_ICONS: Record<NewSessionSuggestionIcon, { Icon: typeof IconBug; type: FileSystemIconType }> = {
    trends: { Icon: IconTrending, type: 'customer_analytics' },
    bug: { Icon: IconBug, type: 'error_tracking' },
    canvas: { Icon: IconPalette, type: 'canvas' },
    code: { Icon: IconCode, type: 'task' },
    revenue: { Icon: IconPiggyBank, type: 'revenue_analytics' },
    feedback: { Icon: IconMessage, type: 'llm_analytics' },
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
                    const { Icon, type } = SUGGESTION_ICONS[suggestion.icon]
                    const [color] = getIconColor(type)
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
