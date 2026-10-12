import { IconBug, IconCode, IconMessage, IconPalette, IconPiggyBank, IconTrending } from '@posthog/icons'
import { Item, ItemContent, ItemDescription, ItemMedia, ItemTitle, Text, cn } from '@posthog/quill-primitives'

import type { PermissionMode } from '../../utils/composerModes'

const STARTER_SUGGESTION_ICONS = {
    trends: IconTrending,
    bug: IconBug,
    canvas: IconPalette,
    code: IconCode,
    revenue: IconPiggyBank,
    feedback: IconMessage,
}

export type ComposerStarterSuggestionIcon = keyof typeof STARTER_SUGGESTION_ICONS

export interface ComposerStarterSuggestion {
    id: string
    label: string
    description: string
    prompt: string
    icon: ComposerStarterSuggestionIcon
    mode?: PermissionMode
}

export interface QuillComposerStarterSuggestionsProps {
    suggestions: ComposerStarterSuggestion[]
    hidden: boolean
    onSelect: (suggestion: ComposerStarterSuggestion, index: number) => void
}

export function QuillComposerStarterSuggestions({
    suggestions,
    hidden,
    onSelect,
}: QuillComposerStarterSuggestionsProps): JSX.Element {
    return (
        <div
            className={cn(
                '@container/starter-suggestions flex flex-col gap-2 transition-[opacity,visibility] duration-200 motion-reduce:transition-none',
                hidden && 'invisible opacity-0'
            )}
        >
            <Text size="xs" variant="muted" weight="medium" className="px-1">
                Suggestions
            </Text>
            <div className="grid grid-cols-1 gap-2 @lg/starter-suggestions:grid-cols-2">
                {suggestions.map((suggestion, index) => {
                    const SuggestionIcon = STARTER_SUGGESTION_ICONS[suggestion.icon]
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
                                    data-attr="task-composer-starter-suggestion"
                                />
                            }
                        >
                            <ItemMedia variant="icon" className="text-muted-foreground">
                                <SuggestionIcon />
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
