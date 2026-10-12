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
    cn,
} from '@posthog/quill-primitives'

import type { PermissionMode } from '../../utils/composerModes'

const STARTER_SUGGESTION_ICONS = {
    trends: { Icon: IconTrending, color: 'var(--color-product-customer-analytics-light)' },
    bug: { Icon: IconBug, color: 'var(--color-product-error-tracking-light)' },
    canvas: { Icon: IconPalette, color: 'var(--color-product-product-analytics-light)' },
    code: { Icon: IconCode, color: 'var(--color-product-tasks-light)' },
    revenue: { Icon: IconPiggyBank, color: 'var(--color-product-revenue-analytics-light)' },
    feedback: { Icon: IconMessage, color: 'var(--color-product-llm-analytics-light)' },
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
    const [activeId, setActiveId] = useState<string | null>(null)

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
                    const { Icon, color } = STARTER_SUGGESTION_ICONS[suggestion.icon]
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
                                    data-attr="task-composer-starter-suggestion"
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
