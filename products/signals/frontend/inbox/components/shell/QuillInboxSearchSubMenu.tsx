import {
    Combobox,
    ComboboxCollection,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    Text,
    cn,
} from '@posthog/quill'

export interface QuillInboxSearchRow {
    /** Unique across every group of the submenu. */
    value: string
    label: string
    /** A muted note after the label, such as "(you)". */
    hint?: string
    tooltip?: string
    /** Runs an action, such as a retry, instead of picking a value. */
    action?: boolean
    dataAttr?: string
    onSelect: () => void
}

export interface QuillInboxSearchGroup {
    key: string
    label?: string
    /** A muted line under the label, such as "Loading…" or why the group is empty. */
    note?: string
    rows: QuillInboxSearchRow[]
}

interface ListGroup {
    key: string
    items: string[]
}

// The search field and rows sit in the menu's popup, whose own key and click handling would close the menu or steal them.
const stopPropagation = (event: React.SyntheticEvent): void => event.stopPropagation()

/**
 * A filter row with one choice from a long or loaded list, under a search field. Quill's `FilterSearchSubMenu`
 * picks several values and filters on its own; the scope and source filters pick one, and their callers filter.
 */
export function QuillInboxSearchSubMenu({
    label,
    value,
    active = false,
    selectedValue,
    groups,
    search,
    onSearchChange,
    searchPlaceholder,
    onOpenChange,
    dataAttr,
}: {
    label: string
    /** The choice in force, shown beside the label. */
    value: string
    /** The choice differs from the default, so the value takes the primary color. */
    active?: boolean
    selectedValue: string | null
    groups: QuillInboxSearchGroup[]
    search: string
    onSearchChange: (search: string) => void
    searchPlaceholder: string
    onOpenChange?: (open: boolean) => void
    dataAttr?: string
}): JSX.Element {
    const rowByValue = new Map(groups.flatMap((group) => group.rows).map((row) => [row.value, row]))
    const groupByKey = new Map(groups.map((group) => [group.key, group]))
    const listGroups: ListGroup[] = groups.map((group) => ({
        key: group.key,
        items: group.rows.map((row) => row.value),
    }))

    return (
        <DropdownMenuSub onOpenChange={(open) => onOpenChange?.(open)}>
            <DropdownMenuSubTrigger data-attr={dataAttr}>
                <span>{label}</span>
                <span
                    title={value}
                    className={cn('flex-1 truncate pl-4 text-right', active ? 'text-primary' : 'text-muted-foreground')}
                >
                    {value}
                </span>
            </DropdownMenuSubTrigger>
            {/* Flush because the list scrolls on its own, under a search field that stays put. */}
            <DropdownMenuSubContent flush className="w-64">
                <Combobox
                    // The submenu is the popup, so the list is always open.
                    inline
                    autoHighlight
                    items={listGroups}
                    // The caller filters the rows, so a search never hides an action.
                    filter={null}
                    value={selectedValue}
                    inputValue={search}
                    itemToStringLabel={(item: string | null) => (item ? (rowByValue.get(item)?.label ?? '') : '')}
                    onInputValueChange={(next: string) => onSearchChange(next)}
                    onValueChange={(next: string | null, { reason }) => {
                        // The list counts as closed while inline, so Base UI treats Escape as a request to clear.
                        if (reason === 'escape-key' || next === null) {
                            return
                        }
                        const row = rowByValue.get(next)
                        if (row && (row.action || next !== selectedValue)) {
                            row.onSelect()
                        }
                    }}
                >
                    <div className="p-1">
                        <ComboboxInput
                            autoFocus
                            showTrigger={false}
                            placeholder={searchPlaceholder}
                            aria-label={searchPlaceholder}
                            data-compact=""
                            onClick={stopPropagation}
                            onKeyDown={(event) => {
                                if (event.key !== 'Escape') {
                                    event.stopPropagation()
                                }
                            }}
                        />
                    </div>
                    <ComboboxList>
                        {(listGroup: ListGroup) => {
                            const group = groupByKey.get(listGroup.key)
                            return (
                                <ComboboxGroup key={listGroup.key} items={listGroup.items}>
                                    {group?.label && <ComboboxLabel>{group.label}</ComboboxLabel>}
                                    {group?.note && (
                                        <Text size="xs" variant="muted" render={<div />} className="px-2 py-1">
                                            {group.note}
                                        </Text>
                                    )}
                                    <ComboboxCollection>
                                        {(item: string) => {
                                            const row = rowByValue.get(item)
                                            return row ? (
                                                <ComboboxItem
                                                    key={item}
                                                    value={item}
                                                    action={row.action}
                                                    title={row.label}
                                                    tooltip={row.tooltip}
                                                    onClick={stopPropagation}
                                                    data-attr={row.dataAttr}
                                                >
                                                    <span className="truncate">{row.label}</span>
                                                    {row.hint && (
                                                        <span className="ml-auto pl-2 text-xs text-muted-foreground">
                                                            {row.hint}
                                                        </span>
                                                    )}
                                                </ComboboxItem>
                                            ) : null
                                        }}
                                    </ComboboxCollection>
                                </ComboboxGroup>
                            )
                        }}
                    </ComboboxList>
                </Combobox>
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}
