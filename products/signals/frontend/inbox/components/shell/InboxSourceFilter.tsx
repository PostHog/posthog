import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput, Spinner } from '@posthog/lemon-ui'

import { inboxSourceFilterLabel } from '../../filterOptions'
import { InboxSourceSelection, inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { scoutFleetLogic } from '../../logics/scoutFleetLogic'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import {
    InboxSourceChoice,
    buildInboxSourceChoices,
    matchesInboxSourceSearch,
    singleInboxSourceSelection,
} from '../../utils/inboxSourceFilter'

function sameSelection(a: InboxSourceSelection | null, b: InboxSourceSelection): boolean {
    return !!a && a.kind === b.kind && a.value === b.value
}

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
                    active={sameSelection(selection, choice)}
                    onClick={() => onSelect(choice)}
                    tooltip={choice.unavailable ? 'This is no longer configured on this project' : undefined}
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
    const { sourceProductFilter, scoutFilter } = useValues(inboxFiltersLogic)
    const { setSourceFilter } = useActions(inboxFiltersLogic)
    const { sourceConfigs, sourceConfigsLoading } = useValues(signalSourcesLogic)
    const { loadSourceConfigs } = useActions(signalSourcesLogic)
    const { scoutConfigs, scoutConfigsLoading } = useValues(scoutFleetLogic)
    const { loadScoutConfigs } = useActions(scoutFleetLogic)
    const [visible, setVisible] = useState(false)
    const [search, setSearch] = useState('')

    const { sources, scouts } = buildInboxSourceChoices({
        sourceConfigs,
        scoutConfigs,
        sourceProductFilter,
        scoutFilter,
    })
    const selection = singleInboxSourceSelection(sourceProductFilter, scoutFilter)
    const hasSelection = sourceProductFilter.length > 0 || scoutFilter.length > 0
    const selectedChoice = selection
        ? [...sources, ...scouts].find((choice) => sameSelection(selection, choice))
        : undefined
    const label = !selectedChoice
        ? inboxSourceFilterLabel(sourceProductFilter, scoutFilter)
        : selectedChoice.kind === 'scout'
          ? `Scout · ${selectedChoice.label}`
          : selectedChoice.label

    const onVisibilityChange = (nextVisible: boolean): void => {
        setVisible(nextVisible)
        setSearch('')
        if (nextVisible && sourceConfigs === null && !sourceConfigsLoading) {
            loadSourceConfigs()
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
                        placeholder="Search sources and scouts"
                        autoFocus
                        value={search}
                        onChange={setSearch}
                        fullWidth
                        aria-label="Search sources and scouts"
                    />
                    <div className="mt-1 max-h-80 overflow-y-auto">
                        <LemonButton
                            size="small"
                            fullWidth
                            active={!hasSelection}
                            onClick={() => pick(null)}
                            data-attr="inbox-filter-source-all"
                        >
                            All sources
                        </LemonButton>
                        <ChoiceSection
                            title="Sources"
                            choices={sources.filter((choice) => matchesInboxSourceSearch(choice, search))}
                            loading={sourceConfigs === null && sourceConfigsLoading}
                            failed={sourceConfigs === null && !sourceConfigsLoading}
                            emptyText={search ? 'No matching sources' : 'No sources configured'}
                            selection={selection}
                            onRetry={loadSourceConfigs}
                            onSelect={pick}
                        />
                        <ChoiceSection
                            title="Scouts"
                            choices={scouts.filter((choice) => matchesInboxSourceSearch(choice, search))}
                            loading={scoutConfigs === null && scoutConfigsLoading}
                            failed={scoutConfigs === null && !scoutConfigsLoading}
                            emptyText={search ? 'No matching scouts' : 'No scouts configured'}
                            selection={selection}
                            onRetry={loadScoutConfigs}
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
