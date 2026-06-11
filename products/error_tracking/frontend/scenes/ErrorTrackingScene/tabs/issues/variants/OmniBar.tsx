import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconSearch } from '@posthog/icons'
import { LemonDropdown } from '@posthog/lemon-ui'

import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { cn } from 'lib/utils/css-classes'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

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

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../../errorTrackingSceneLogic'

export const QUICK_FILTER_CONTEXT = QuickFilterContext.ErrorTrackingIssueFilters

/** Vertical hairline used between control groups inside the bar. */
export const OmniBarSeparator = (): JSX.Element => <div className="w-px h-5 bg-border shrink-0 mx-1" />

export interface OmniBarProps {
    /** Controls rendered inside the bar, before the search icon. */
    leading?: React.ReactNode
    /** Controls rendered inside the bar, at the right edge. */
    trailing?: React.ReactNode
    /** Tokens rendered at the very start of the input, before any chips. */
    prefixTokens?: React.ReactNode
    /** Second row rendered inside the same frame, under a hairline. */
    secondRow?: React.ReactNode
    /** Status/assignee chips inside the input. @default true */
    showIssueChips?: boolean
    /** Internal-users + quick filter chips inside the input. @default true */
    showContextChips?: boolean
    /** Active property filter chips inside the input. @default true */
    showFilterChips?: boolean
    /** @default true */
    showKbdHint?: boolean
    placeholder?: string
    className?: string
}

/**
 * Shared hero search bar: one large, keyboard-first command bar wired to the
 * taxonomic filter. Pressing `/` anywhere focuses it. Variants compose the
 * slots (leading/trailing/prefixTokens/secondRow) to shuffle the layout.
 */
export function OmniBar(props: OmniBarProps): JSX.Element {
    const { filterGroup } = useValues(issueFiltersLogic)
    const { setFilterGroup } = useActions(issueFiltersLogic)

    return (
        <UniversalFilters
            rootKey={TAXONOMIC_FILTER_LOGIC_KEY}
            group={filterGroup.values[0] as UniversalFiltersGroup}
            taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES}
            onChange={(group) => setFilterGroup({ type: FilterLogicalOperator.And, values: [group] })}
        >
            <OmniBarFrame {...props} />
        </UniversalFilters>
    )
}

const OmniBarFrame = ({
    leading,
    trailing,
    prefixTokens,
    secondRow,
    showIssueChips = true,
    showContextChips = true,
    showFilterChips = true,
    showKbdHint = true,
    placeholder = 'Search issues, or start typing a property to filter...',
    className,
}: OmniBarProps): JSX.Element => {
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
                    className={cn(
                        'rounded-lg border bg-[var(--color-bg-fill-input)] shadow-sm transition-colors focus-within:border-[var(--color-border-bold)] [&_.LemonInput]:border-0 [&_.LemonInput]:shadow-none [&_.LemonInput]:bg-transparent',
                        className
                    )}
                >
                    <div
                        className="flex items-center min-h-11 pr-1.5"
                        onFocus={() => setFocused(true)}
                        onBlur={() => setFocused(false)}
                    >
                        {leading && (
                            <>
                                <div className="flex items-center gap-0.5 pl-1.5 shrink-0">{leading}</div>
                                <OmniBarSeparator />
                            </>
                        )}
                        <IconSearch className={cn('text-lg text-muted shrink-0', leading ? 'ml-1' : 'ml-3')} />
                        <div className="flex-1 min-w-0">
                            <TaxonomicFilterSearchInput
                                prefix={
                                    <>
                                        {prefixTokens}
                                        {showIssueChips && <IssueFilterChips />}
                                        {showContextChips && (
                                            <>
                                                <InternalUsersChip />
                                                <QuickFilterChips
                                                    context={QUICK_FILTER_CONTEXT}
                                                    logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                                                />
                                            </>
                                        )}
                                        {showFilterChips && (
                                            <UniversalFilterGroup taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES} />
                                        )}
                                    </>
                                }
                                onClick={() => setVisible(true)}
                                searchInputRef={searchInputRef}
                                onClose={() => onClose()}
                                onChange={onChange}
                                size="small"
                                autoFocus={false}
                                fullWidth
                                placeholder={placeholder}
                            />
                        </div>
                        {showKbdHint && !focused && (
                            <kbd className="hidden md:inline-flex items-center justify-center shrink-0 rounded border px-1.5 h-5 mr-1 text-xs text-muted font-mono">
                                /
                            </kbd>
                        )}
                        {trailing && (
                            <>
                                <OmniBarSeparator />
                                <div className="flex items-center gap-0.5 shrink-0">{trailing}</div>
                            </>
                        )}
                    </div>
                    {secondRow && (
                        <div className="flex items-center gap-1.5 flex-wrap border-t px-2 py-1.5">{secondRow}</div>
                    )}
                </div>
            </LemonDropdown>
        </BindLogic>
    )
}
