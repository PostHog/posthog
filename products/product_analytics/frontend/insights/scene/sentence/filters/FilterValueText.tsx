import { useActions } from 'kea'

import {
    Autocomplete,
    AutocompleteContent,
    AutocompleteEmpty,
    AutocompleteInput,
    AutocompleteItem,
    AutocompleteList,
    Input,
} from '@posthog/quill'

import { filtersEditorLogic } from './filtersEditorLogic'
import type { EditableFilterRowView } from './filtersEditorLogic'
import { suggestionsEmptyText } from './suggestionsEmptyText'

export function FilterValueText({ row, inputId }: { row: EditableFilterRowView; inputId: string }): JSX.Element {
    const { changeFilterValue, searchFilterValues } = useActions(filtersEditorLogic)
    const value = row.values[0] ?? ''

    if (row.suggestionsStatus === 'none') {
        return (
            <Input
                id={inputId}
                value={value}
                placeholder={row.valuePlaceholder}
                onChange={(event: React.ChangeEvent<HTMLInputElement>) => changeFilterValue(row.id, event.target.value)}
                data-attr="quill-insight-filters-value"
            />
        )
    }

    return (
        // Highlighting the first suggestion would make Enter replace the typed text with it.
        <Autocomplete
            items={row.valueOptions}
            value={value}
            onValueChange={(text: string) => changeFilterValue(row.id, text)}
            autoHighlight={false}
        >
            <AutocompleteInput
                id={inputId}
                showSearchIcon={false}
                placeholder={row.valuePlaceholder}
                onFocus={() => searchFilterValues(row.id, value)}
                data-attr="quill-insight-filters-value"
            />
            <AutocompleteContent>
                <AutocompleteEmpty>{suggestionsEmptyText(row.suggestionsStatus)}</AutocompleteEmpty>
                <AutocompleteList>
                    {(item: string) => (
                        <AutocompleteItem key={item} value={item} nativeButton>
                            {item}
                        </AutocompleteItem>
                    )}
                </AutocompleteList>
            </AutocompleteContent>
        </Autocomplete>
    )
}
