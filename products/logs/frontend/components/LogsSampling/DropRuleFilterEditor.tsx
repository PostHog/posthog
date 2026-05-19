import { BindLogic, useActions, useValues } from 'kea'
import { memo, useCallback, useId, useMemo, useRef, useState } from 'react'

import { LemonDropdown } from '@posthog/lemon-ui'

import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

// Namespace prefix only — the real per-mount key is appended below so that two
// editors mounted simultaneously (e.g. during fast scene navigation) don't share
// universalFiltersLogic / taxonomicFilterLogic instances.
const ROOT_KEY_PREFIX = 'logs-drop-rule'
const TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.Logs,
    TaxonomicFilterGroupType.LogResourceAttributes,
    TaxonomicFilterGroupType.LogAttributes,
]

export const DropRuleFilterEditor = memo(function DropRuleFilterEditor({
    filterGroup,
    onChange,
    logicKey,
}: {
    filterGroup: UniversalFiltersGroup
    onChange: (group: UniversalFiltersGroup) => void
    /** Optional explicit key (e.g. `rule-${id}`); defaults to a per-mount React id. */
    logicKey?: string
}): JSX.Element {
    const fallback = useId()
    const rootKey = logicKey ?? `${ROOT_KEY_PREFIX}:${fallback}`
    return (
        <UniversalFilters
            rootKey={rootKey}
            group={filterGroup}
            taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES}
            onChange={onChange}
        >
            <div className="space-y-2">
                <DropRuleFilterSearch logicKey={rootKey} />
                <DropRuleAppliedFilters />
            </div>
        </UniversalFilters>
    )
})

function DropRuleFilterSearch({ logicKey }: { logicKey: string }): JSX.Element {
    const [visible, setVisible] = useState<boolean>(false)
    const { addGroupFilter, setGroupValues } = useActions(universalFiltersLogic)
    const { filterGroup } = useValues(universalFiltersLogic)

    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const floatingRef = useRef<HTMLDivElement | null>(null)
    const filterGroupRef = useRef(filterGroup)
    filterGroupRef.current = filterGroup

    const onClose = useCallback((): void => {
        searchInputRef.current?.blur()
        setVisible(false)
    }, [])

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = useMemo(
        () => ({
            taxonomicFilterLogicKey: logicKey,
            taxonomicGroupTypes: TAXONOMIC_GROUP_TYPES,
            onChange: (taxonomicGroup, value, item) => {
                if (item.value === undefined) {
                    addGroupFilter(taxonomicGroup, value, item)
                    setVisible(false)
                    return
                }

                const newValues = [...filterGroupRef.current.values]
                const newPropertyFilter = {
                    key: item.key,
                    value: item.value,
                    operator: PropertyOperator.IContains,
                    type: item.propertyFilterType,
                } as AnyPropertyFilter
                newValues.push(newPropertyFilter)
                setGroupValues(newValues)
                setVisible(false)
            },
            onEnter: () => {
                searchInputRef.current?.blur()
                setVisible(false)
            },
            autoSelectItem: true,
        }),
        [addGroupFilter, setGroupValues, logicKey]
    )

    const showDropdown = useCallback(() => setVisible(true), [])

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <LemonDropdown
                overlay={
                    <div className="w-[400px]">
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
                onClickOutside={onClose}
            >
                <TaxonomicFilterSearchInput
                    onClick={showDropdown}
                    searchInputRef={searchInputRef}
                    onClose={onClose}
                    onChange={showDropdown}
                />
            </LemonDropdown>
        </BindLogic>
    )
}

function DropRuleAppliedFilters(): JSX.Element | null {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    if (filterGroup.values.length === 0) {
        return null
    }

    return (
        <div className="flex gap-1 items-center flex-wrap">
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group index={index} key={index} group={filterOrGroup}>
                        <DropRuleAppliedFilters />
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                        initiallyOpen={filterOrGroup.type !== PropertyFilterType.HogQL}
                    />
                )
            })}
        </div>
    )
}
