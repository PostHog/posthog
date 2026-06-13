import {
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    useComboboxAnchor,
} from '@posthog/quill-primitives'

interface CategoryScopeSelectProps {
    categories: string[]
    value: string[]
    loading: boolean
    onChange: (categories: string[]) => void
}

function CategoryScopeSelectInner({ value, loading }: { value: string[]; loading: boolean }): JSX.Element {
    const anchor = useComboboxAnchor()
    return (
        <>
            <ComboboxChips ref={anchor}>
                <ComboboxValue>
                    {(values: string[]) => (
                        <>
                            {values.map((category) => (
                                <ComboboxChip key={category} title={category}>
                                    {category}
                                </ComboboxChip>
                            ))}
                            <ComboboxChipsInput placeholder={value.length === 0 ? 'All categories' : ''} />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>{loading ? 'Loading categories…' : 'No categories found'}</ComboboxEmpty>
                <ComboboxList>
                    {(category: string) => (
                        <ComboboxItem key={category} value={category}>
                            {category}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}

export function CategoryScopeSelect({ categories, value, loading, onChange }: CategoryScopeSelectProps): JSX.Element {
    return (
        <Combobox multiple autoHighlight items={categories} value={value} onValueChange={onChange}>
            <CategoryScopeSelectInner value={value} loading={loading} />
        </Combobox>
    )
}
