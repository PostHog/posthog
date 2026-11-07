import { useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput, Spinner } from '@posthog/lemon-ui'

import { InboxSourceSelection } from '../../logics/inboxFiltersLogic'
import { InboxSourceChoice, matchesInboxSourceSearch } from '../../utils/inboxSourceFilter'
import {
    INBOX_ALL_SOURCES_LABEL,
    INBOX_SOURCE_GROUP_TITLE,
    INBOX_SOURCE_SEARCH_PLACEHOLDER,
    INBOX_SOURCE_UNAVAILABLE_REASON,
    inboxSourceEmptyText,
    sameInboxSourceSelection,
    useInboxSourceFilter,
} from './useInboxSourceFilter'

function ChoiceSection({
    title,
    choices,
    loading,
    failed,
    emptyText,
    selection,
    onRetry,
    onSelect,
}: {
    title: string
    choices: InboxSourceChoice[]
    loading: boolean
    failed: boolean
    emptyText: string
    selection: InboxSourceSelection | null
    onRetry: () => void
    onSelect: (choice: InboxSourceChoice) => void
}): JSX.Element {
    return (
        <div role="group" aria-label={title}>
            <div className="px-2 pt-2 pb-1 text-xs font-semibold text-secondary">{title}</div>
            {choices.map((choice) => (
                <LemonButton
                    key={`${choice.kind}:${choice.value}`}
                    size="small"
                    fullWidth
                    active={sameInboxSourceSelection(selection, choice)}
                    onClick={() => onSelect(choice)}
                    tooltip={choice.unavailable ? INBOX_SOURCE_UNAVAILABLE_REASON : undefined}
                    data-attr={`inbox-filter-source-${choice.kind}`}
                >
                    <span className="truncate">
                        {choice.label}
                        {choice.unavailable && <span className="text-muted"> · unavailable</span>}
                    </span>
                </LemonButton>
            ))}
            {loading ? (
                <div className="flex items-center gap-2 px-2 py-1 text-xs text-muted">
                    <Spinner /> Loading…
                </div>
            ) : failed ? (
                <div className="flex items-center gap-2 px-2 py-1 text-xs text-muted">
                    Couldn't load this list.
                    <LemonButton size="xsmall" type="tertiary" onClick={onRetry}>
                        Try again
                    </LemonButton>
                </div>
            ) : choices.length === 0 ? (
                <div className="px-2 py-1 text-xs text-muted">{emptyText}</div>
            ) : null}
        </div>
    )
}

/**
 * Single-select Source filter for the Reports list: one configured product, or one scout. The choices
 * come from the source and scout configs, not from the loaded reports, so every page is reachable.
 */
export function InboxSourceFilter(): JSX.Element {
    const { sources, scouts, selection, hasSelection, label, ensureSourceConfigs, setSourceFilter } =
        useInboxSourceFilter()
    const [visible, setVisible] = useState(false)
    const [search, setSearch] = useState('')

    const onVisibilityChange = (nextVisible: boolean): void => {
        setVisible(nextVisible)
        setSearch('')
        if (nextVisible) {
            ensureSourceConfigs()
        }
    }
    const pick = (next: InboxSourceSelection | null): void => {
        setSourceFilter(next)
        onVisibilityChange(false)
    }

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={visible}
            onVisibilityChange={onVisibilityChange}
            matchWidth={false}
            actionable
            placement="bottom-start"
            overlay={
                <div className="flex w-72 max-w-[calc(100vw-2rem)] flex-col">
                    <LemonInput
                        type="search"
                        size="small"
                        placeholder={INBOX_SOURCE_SEARCH_PLACEHOLDER}
                        autoFocus
                        value={search}
                        onChange={setSearch}
                        fullWidth
                        aria-label={INBOX_SOURCE_SEARCH_PLACEHOLDER}
                    />
                    <div className="mt-1 max-h-80 overflow-y-auto">
                        <LemonButton
                            size="small"
                            fullWidth
                            active={!hasSelection}
                            onClick={() => pick(null)}
                            data-attr="inbox-filter-source-all"
                        >
                            {INBOX_ALL_SOURCES_LABEL}
                        </LemonButton>
                        <ChoiceSection
                            title={INBOX_SOURCE_GROUP_TITLE.source_product}
                            choices={sources.choices.filter((choice) => matchesInboxSourceSearch(choice, search))}
                            loading={sources.loading}
                            failed={sources.failed}
                            emptyText={inboxSourceEmptyText('source_product', !!search)}
                            selection={selection}
                            onRetry={sources.retry}
                            onSelect={pick}
                        />
                        <ChoiceSection
                            title={INBOX_SOURCE_GROUP_TITLE.scout}
                            choices={scouts.choices.filter((choice) => matchesInboxSourceSearch(choice, search))}
                            loading={scouts.loading}
                            failed={scouts.failed}
                            emptyText={inboxSourceEmptyText('scout', !!search)}
                            selection={selection}
                            onRetry={scouts.retry}
                            onSelect={pick}
                        />
                    </div>
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                aria-label={`Source: ${label}`}
                sideAction={
                    hasSelection
                        ? {
                              icon: <IconX />,
                              tooltip: 'Show all sources',
                              'aria-label': 'Show all sources',
                              onClick: () => setSourceFilter(null),
                              'data-attr': 'inbox-filter-source-clear',
                          }
                        : undefined
                }
                data-attr="inbox-filter-source"
            >
                <span className="max-w-[200px] truncate">{label}</span>
            </LemonButton>
        </LemonDropdown>
    )
}
