import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconFilter, IconSearch, IconSort, IconTriangleDown, IconTriangleUp } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonMenu } from '@posthog/lemon-ui'

import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'
import {
    TAXONOMIC_FILTER_LOGIC_KEY,
    TAXONOMIC_GROUP_TYPES,
} from 'products/error_tracking/frontend/components/IssueFilters/consts'
import {
    InternalUsersChip,
    IssueFilterChips,
    QuickFilterChips,
    UniversalFilterGroup,
} from 'products/error_tracking/frontend/components/IssueFilters/FilterGroup'
import { issueFiltersLogic } from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'
import {
    ErrorTrackingQueryOrderBy,
    ORDER_BY_OPTIONS,
    issueQueryOptionsLogic,
} from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../../errorTrackingSceneLogic'
import { ListReloadButton } from '../IssuesList'

const QUICK_FILTER_CONTEXT = QuickFilterContext.ErrorTrackingIssueFilters

/**
 * Variant B — "Hero omnibar, scope first".
 * One large, keyboard-first command bar. Reading order matches the mental
 * model: actions and scope on the left edge (reload, date range, filter
 * settings), the query in the middle, arrangement on the right with sort
 * field and direction as two one-click buttons. `/` focuses search.
 */
export function IssuesFiltersB(): JSX.Element {
    const { filterGroup } = useValues(issueFiltersLogic)
    const { setFilterGroup } = useActions(issueFiltersLogic)

    return (
        <UniversalFilters
            rootKey={TAXONOMIC_FILTER_LOGIC_KEY}
            group={filterGroup.values[0] as UniversalFiltersGroup}
            taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES}
            onChange={(group) => setFilterGroup({ type: FilterLogicalOperator.And, values: [group] })}
        >
            <OmniBar />
        </UniversalFilters>
    )
}

const Separator = (): JSX.Element => <div className="w-px h-5 bg-border shrink-0 mx-1" />

const OmniBar = (): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)
    const [focused, setFocused] = useState<boolean>(false)
    const { searchQuery } = useValues(issueFiltersLogic)
    const { setSearchQuery } = useActions(issueFiltersLogic)
    const { addGroupFilter } = useActions(universalFiltersLogic)

    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const floatingRef = useRef<HTMLDivElement | null>(null)

    const onClose = (): void => {
        searchInputRef.current?.blur()
        setVisible(false)
    }

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey: TAXONOMIC_FILTER_LOGIC_KEY,
        taxonomicGroupTypes: TAXONOMIC_GROUP_TYPES,
        onChange: (taxonomicGroup, value, item) => {
            searchInputRef.current?.blur()
            setVisible(false)
            setSearchQuery('')
            addGroupFilter(taxonomicGroup, value, item)
        },
        onEnter: onClose,
        autoSelectItem: false,
        initialSearchQuery: searchQuery,
        excludedProperties: { [TaxonomicFilterGroupType.ErrorTrackingIssues]: ['assignee'] },
    }

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) {
                return
            }
            const target = event.target as HTMLElement | null
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
                return
            }
            event.preventDefault()
            searchInputRef.current?.focus()
            setVisible(true)
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [])

    const onChange = useDebouncedCallback((value: string) => setSearchQuery(value), 250)

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <LemonDropdown
                overlay={
                    <div className="w-[400px] md:w-[640px]">
                        <InfiniteSelectResults
                            focusInput={() => searchInputRef.current?.focus()}
                            taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                            popupAnchorElement={floatingRef.current}
                        />
                    </div>
                }
                visible={visible}
                closeOnClickInside={false}
                floatingRef={floatingRef}
                onClickOutside={() => onClose()}
            >
                <div
                    className="flex items-center min-h-11 pr-1.5 rounded-lg border bg-[var(--color-bg-fill-input)] shadow-sm transition-colors focus-within:border-[var(--color-border-bold)] [&_.LemonInput]:border-0 [&_.LemonInput]:shadow-none [&_.LemonInput]:bg-transparent"
                    onFocus={() => setFocused(true)}
                    onBlur={() => setFocused(false)}
                >
                    <div className="flex items-center gap-0.5 pl-1.5 shrink-0">
                        <ListReloadButton />
                        <ErrorFilters.DateRange size="small" type="tertiary" />
                        <ErrorFilters.SettingsMenu
                            icon={<IconFilter />}
                            quickFilterContext={QUICK_FILTER_CONTEXT}
                            logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                        />
                    </div>
                    <Separator />
                    <IconSearch className="ml-1 text-lg text-muted shrink-0" />
                    <div className="flex-1 min-w-0">
                        <TaxonomicFilterSearchInput
                            prefix={
                                <>
                                    <IssueFilterChips />
                                    <InternalUsersChip />
                                    <QuickFilterChips
                                        context={QUICK_FILTER_CONTEXT}
                                        logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                                    />
                                    <UniversalFilterGroup taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES} />
                                </>
                            }
                            onClick={() => setVisible(true)}
                            searchInputRef={searchInputRef}
                            onClose={() => onClose()}
                            onChange={onChange}
                            size="small"
                            autoFocus={false}
                            fullWidth
                            placeholder="Search issues, or start typing a property to filter..."
                        />
                    </div>
                    {!focused && (
                        <kbd className="hidden md:inline-flex items-center justify-center shrink-0 rounded border px-1.5 h-5 mr-1 text-xs text-muted font-mono">
                            /
                        </kbd>
                    )}
                    <Separator />
                    <div className="flex items-center gap-0.5 shrink-0">
                        <SortFieldButton />
                        <SortDirectionButton />
                    </div>
                </div>
            </LemonDropdown>
        </BindLogic>
    )
}

const SortFieldButton = (): JSX.Element => {
    const { orderBy } = useValues(issueQueryOptionsLogic)
    const { setOrderBy } = useActions(issueQueryOptionsLogic)

    return (
        <LemonMenu
            items={Object.entries(ORDER_BY_OPTIONS).map(([value, label]) => ({
                label,
                active: orderBy === value,
                onClick: () => setOrderBy(value as ErrorTrackingQueryOrderBy),
            }))}
        >
            <LemonButton size="small" type="tertiary" icon={<IconSort />} tooltip="Sort by">
                {ORDER_BY_OPTIONS[orderBy]}
            </LemonButton>
        </LemonMenu>
    )
}

const SortDirectionButton = (): JSX.Element => {
    const { orderDirection } = useValues(issueQueryOptionsLogic)
    const { setOrderDirection } = useActions(issueQueryOptionsLogic)

    return (
        <LemonButton
            size="small"
            type="tertiary"
            icon={orderDirection === 'DESC' ? <IconTriangleDown /> : <IconTriangleUp />}
            onClick={() => setOrderDirection(orderDirection === 'DESC' ? 'ASC' : 'DESC')}
            tooltip={
                orderDirection === 'DESC'
                    ? 'Newest first — click for oldest first'
                    : 'Oldest first — click for newest first'
            }
        />
    )
}
