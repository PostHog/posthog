import { useState } from 'react'

import { InboxSourceChoice, matchesInboxSourceSearch } from '../../utils/inboxSourceFilter'
import { QuillInboxSearchGroup, QuillInboxSearchRow, QuillInboxSearchSubMenu } from './QuillInboxSearchSubMenu'
import {
    INBOX_ALL_SOURCES_LABEL,
    INBOX_SOURCE_GROUP_TITLE,
    INBOX_SOURCE_SEARCH_PLACEHOLDER,
    INBOX_SOURCE_UNAVAILABLE_REASON,
    InboxSourceChoiceList,
    inboxSourceEmptyText,
    useInboxSourceFilter,
} from './useInboxSourceFilter'

const ALL_SOURCES_VALUE = 'all'
const choiceRowValue = (choice: { kind: string; value: string }): string => `${choice.kind}:${choice.value}`

/** The quill sibling of `InboxSourceFilter`, as a row of the filter menu: one configured product, or one scout. */
export function QuillInboxSourceSubMenu(): JSX.Element {
    const { sources, scouts, selection, hasSelection, label, ensureSourceConfigs, setSourceFilter } =
        useInboxSourceFilter()
    const [search, setSearch] = useState('')

    const group = (kind: InboxSourceChoice['kind'], list: InboxSourceChoiceList): QuillInboxSearchGroup => {
        const choices = list.choices.filter((choice) => matchesInboxSourceSearch(choice, search))
        const rows: QuillInboxSearchRow[] = choices.map((choice) => ({
            value: choiceRowValue(choice),
            label: choice.label,
            hint: choice.unavailable ? 'unavailable' : undefined,
            tooltip: choice.unavailable ? INBOX_SOURCE_UNAVAILABLE_REASON : undefined,
            dataAttr: `inbox-filter-source-${choice.kind}`,
            onSelect: () => setSourceFilter({ kind: choice.kind, value: choice.value }),
        }))
        if (list.failed) {
            rows.push({ value: `retry:${kind}`, label: 'Try again', action: true, onSelect: list.retry })
        }
        return {
            key: kind,
            label: INBOX_SOURCE_GROUP_TITLE[kind],
            note: list.loading
                ? 'Loading…'
                : list.failed
                  ? "Couldn't load this list."
                  : choices.length === 0
                    ? inboxSourceEmptyText(kind, !!search)
                    : undefined,
            rows,
        }
    }

    return (
        <QuillInboxSearchSubMenu
            label="Source"
            value={label}
            active={hasSelection}
            selectedValue={selection ? choiceRowValue(selection) : hasSelection ? null : ALL_SOURCES_VALUE}
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder={INBOX_SOURCE_SEARCH_PLACEHOLDER}
            onOpenChange={(open) => {
                setSearch('')
                if (open) {
                    ensureSourceConfigs()
                }
            }}
            groups={[
                {
                    key: ALL_SOURCES_VALUE,
                    rows: [
                        {
                            value: ALL_SOURCES_VALUE,
                            label: INBOX_ALL_SOURCES_LABEL,
                            dataAttr: 'inbox-filter-source-all',
                            onSelect: () => setSourceFilter(null),
                        },
                    ],
                },
                group('source_product', sources),
                group('scout', scouts),
            ]}
            dataAttr="inbox-filter-source"
        />
    )
}
