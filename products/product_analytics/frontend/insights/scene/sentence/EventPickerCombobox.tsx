import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    Button,
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    ComboboxListFooter,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Spinner,
    Text,
} from '@posthog/quill'

import type { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { EVENT_PICKER_GROUP_LIMIT, eventPickerLogic } from './eventPickerLogic'
import type { EventPickerGroup, EventPickerItem, EventPickerLogicProps } from './eventPickerLogic'

const GROUP_LABELS: Record<EventPickerGroup['value'], string> = { events: 'Events', actions: 'Actions' }

export interface EventPickerComboboxProps extends EventPickerLogicProps {
    anchor: () => Element | null
    /** Shown under the list, for actions on the event the picker was opened from. */
    footer?: React.ReactNode
    onPick: (groupType: TaxonomicFilterGroupType, value: string | number | null, name?: string) => void
    onClose: (returnFocus: boolean) => void
}

export function EventPickerCombobox({
    anchor,
    footer,
    onPick,
    onClose,
    ...logicProps
}: EventPickerComboboxProps): JSX.Element {
    const logic = eventPickerLogic(logicProps)
    const { search, groups, selectedItem, eventsLoadFailed } = useValues(logic)
    const { setSearch, loadEvents } = useActions(logic)
    const searchInputId = useId()

    return (
        <Combobox
            items={groups}
            filteredItems={groups}
            open
            onOpenChange={(nextOpen, eventDetails) => {
                if (nextOpen) {
                    return
                }
                const target = eventDetails.event.target
                // A press on the trigger counts as outside, and would close then reopen on the click.
                if (eventDetails.reason === 'outside-press' && target instanceof Node && anchor()?.contains(target)) {
                    eventDetails.cancel()
                    return
                }
                onClose(eventDetails.reason === 'escape-key' || eventDetails.reason === 'item-press')
            }}
            inputValue={search}
            onInputValueChange={(nextSearch) => setSearch(nextSearch)}
            value={selectedItem}
            onValueChange={(item) => {
                if (item && item.id !== selectedItem?.id) {
                    onPick(item.groupType, item.value, item.name)
                }
            }}
            isItemEqualToValue={(item, selected) => item.id === selected.id}
            itemToStringLabel={(item) => item.label}
            autoHighlight
        >
            <ComboboxContent anchor={anchor} className="w-80">
                <ComboboxInput
                    id={searchInputId}
                    placeholder="Search events and actions"
                    showTrigger={false}
                    data-attr="quill-insight-event-picker-search"
                />
                {eventsLoadFailed && (
                    <div className="p-1">
                        <Item size="xs" tone="destructive" role="alert">
                            <ItemContent>
                                <ItemTitle>Couldn't load events</ItemTitle>
                            </ItemContent>
                            <ItemActions>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => {
                                        document.getElementById(searchInputId)?.focus()
                                        loadEvents()
                                    }}
                                    data-attr="quill-insight-event-picker-retry"
                                >
                                    Try again
                                </Button>
                            </ItemActions>
                        </Item>
                    </div>
                )}
                <ComboboxEmpty>
                    {!eventsLoadFailed && (
                        <span>{`No events or actions match "${search.trim()}". Try a different search.`}</span>
                    )}
                </ComboboxEmpty>
                <ComboboxList>
                    {(group: EventPickerGroup) => (
                        <ComboboxGroup key={group.value} items={group.items}>
                            <ComboboxLabel>{GROUP_LABELS[group.value]}</ComboboxLabel>
                            <ComboboxCollection>
                                {(item: EventPickerItem) => (
                                    <ComboboxItem
                                        key={item.id}
                                        value={item}
                                        title={item.label}
                                        data-attr="quill-insight-event-picker-row"
                                    >
                                        <span className="truncate">{item.label}</span>
                                        {item.name !== undefined && item.name !== item.label && (
                                            <Text size="xs" variant="muted" render={<span />} className="truncate">
                                                {item.name}
                                            </Text>
                                        )}
                                    </ComboboxItem>
                                )}
                            </ComboboxCollection>
                            {group.loading && (
                                <Item size="xs" role="status">
                                    <ItemMedia>
                                        <Spinner aria-hidden />
                                    </ItemMedia>
                                    <ItemContent>
                                        <ItemDescription>{`Loading ${group.value}`}</ItemDescription>
                                    </ItemContent>
                                </Item>
                            )}
                            {group.capped && (
                                <Item size="xs">
                                    <ItemContent>
                                        <ItemDescription>
                                            {`Showing the first ${EVENT_PICKER_GROUP_LIMIT} ${group.value}. Search to find more.`}
                                        </ItemDescription>
                                    </ItemContent>
                                </Item>
                            )}
                        </ComboboxGroup>
                    )}
                </ComboboxList>
                {footer && <ComboboxListFooter>{footer}</ComboboxListFooter>}
            </ComboboxContent>
        </Combobox>
    )
}
