import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill-primitives'

import type { SuggestionGroup, SuggestionItem } from '../suggestions/Suggestions'

export interface QuillSuggestionChipsProps {
    data: readonly SuggestionGroup[]
    onSelect: (item: SuggestionItem) => void
}

export function QuillSuggestionChips({ data, onSelect }: QuillSuggestionChipsProps): JSX.Element {
    return (
        <ul data-quill className="m-0 flex list-none flex-wrap items-center justify-center gap-1.5 p-0">
            {data.map((group) => (
                <li key={group.label}>
                    {group.suggestions.length === 1 ? (
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => onSelect(group.suggestions[0])}
                            data-attr={group.suggestions[0].dataAttr}
                        >
                            {group.icon}
                            {group.label}
                        </Button>
                    ) : (
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={
                                    <Button variant="outline" size="sm">
                                        {group.icon}
                                        {group.label}
                                    </Button>
                                }
                            />
                            <DropdownMenuContent align="center" side="bottom" sideOffset={6} className="min-w-fit">
                                {group.suggestions.map((suggestion) => (
                                    <DropdownMenuItem
                                        key={suggestion.content}
                                        onClick={() => onSelect(suggestion)}
                                        data-attr={suggestion.dataAttr}
                                    >
                                        {suggestion.content}
                                    </DropdownMenuItem>
                                ))}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )}
                </li>
            ))}
        </ul>
    )
}
