import { ItemCheckbox, ItemContent, ItemDescription, ItemTitle, ToggleGroup, ToggleGroupItem } from 'lib/ui/quill'

import type { ErrorTrackingIssueTagDefinitionApi } from '../../generated/api.schemas'
import type { IssueTagState } from '../IssueQueryOptions/issueQueryOptionsLogic'

const TAG_STATE_OPTIONS: { value: IssueTagState; label: string; dataAttr: string }[] = [
    { value: 'has', label: 'Has', dataAttr: 'error-tracking-issue-tag-filter-has' },
    { value: 'hasNot', label: 'Has not', dataAttr: 'error-tracking-issue-tag-filter-has-not' },
]

export function IssueTagRow({
    definition,
    state,
    onChange,
}: {
    definition: Pick<ErrorTrackingIssueTagDefinitionApi, 'label' | 'description'>
    state: IssueTagState | null
    onChange: (state: IssueTagState | null) => void
}): JSX.Element {
    return (
        <div className="flex items-center gap-1 rounded-sm px-1 hover:bg-fill-hover">
            <ItemCheckbox
                size="xs"
                aria-checked={state !== null}
                className="min-w-0 flex-1 p-0 text-left hover:bg-transparent"
                data-attr="error-tracking-issue-tag-filter-checkbox"
                onClick={() => onChange(state ? null : 'has')}
            >
                <ItemContent variant="menuItem" className="min-w-0 gap-0.5">
                    <ItemTitle className="block w-full min-w-0 truncate font-normal">{definition.label}</ItemTitle>
                    {definition.description && (
                        <ItemDescription className="line-clamp-1" title={definition.description}>
                            {definition.description}
                        </ItemDescription>
                    )}
                </ItemContent>
            </ItemCheckbox>
            <ToggleGroup
                size="sm"
                aria-label={`${definition.label} filter`}
                value={state ? [state] : []}
                // Pressing the pressed button again empties the group, which removes the tag from the filter.
                onValueChange={(next: string[]) =>
                    onChange(TAG_STATE_OPTIONS.find((option) => option.value === next[0])?.value ?? null)
                }
            >
                {TAG_STATE_OPTIONS.map((option) => (
                    <ToggleGroupItem
                        key={option.value}
                        value={option.value}
                        data-attr={option.dataAttr}
                        // Quill shows a pressed toggle only as pushed in, and next to a raised button the pushed-in one
                        // looks like the one that is off. The text color and the fill mark which one is pressed.
                        className="text-(--muted-foreground) aria-pressed:bg-(--fill-selected) aria-pressed:text-(--foreground)"
                    >
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}
