import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'

import { customFacetsLogic } from './customFacetsLogic'
import { facetPresenceLogic } from './facetPresenceLogic'
import { facetRailLogic } from './facetRailLogic'
import { facetsByGroup, filterFacetsByName } from './facets'
import { RailFacet } from './RailFacet'

const DEFAULT_WIDTH_PX = 240
const COLLAPSE_THRESHOLD_PX = 120
const ADD_FACET_GROUP_TYPES = [TaxonomicFilterGroupType.LogAttributes, TaxonomicFilterGroupType.LogResourceAttributes]

export interface FacetRailProps {
    id: string
}

/** Resizable left-hand facet rail, rendered entirely from the FACETS config (see facets.ts). */
export function FacetRail({ id }: FacetRailProps): JSX.Element {
    const railRef = useRef<HTMLDivElement>(null)
    const { setFacetRailCollapsed } = useActions(logsViewerConfigLogic)
    const { visibleFacets } = useValues(facetPresenceLogic({ id }))
    const { facetNameSearch } = useValues(facetRailLogic({ id }))
    const { setFacetNameSearch } = useActions(facetRailLogic({ id }))
    const { addCustomFacet } = useActions(customFacetsLogic)
    const { customFacetsEnabled, entriesLoading } = useValues(customFacetsLogic)

    const onToggleClosed = useCallback(
        (shouldBeClosed: boolean) => setFacetRailCollapsed(shouldBeClosed),
        [setFacetRailCollapsed]
    )
    const resizerLogicProps: ResizerLogicProps = useMemo(
        () => ({
            logicKey: `logs-facet-rail-${id}`,
            containerRef: railRef,
            persistent: true,
            persistPrefix: '2026-06-18',
            placement: 'right',
            closeThreshold: COLLAPSE_THRESHOLD_PX,
            onToggleClosed,
        }),
        [id, onToggleClosed]
    )
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    // Every visible facet renders a container, whether or not the field-name search matches it: a
    // non-matching one renders nothing but stays mounted, so clearing the search doesn't refetch.
    const matchingKeys = new Set(filterFacetsByName(visibleFacets, facetNameSearch).map((f) => f.key))
    const groups = facetsByGroup(visibleFacets)

    return (
        <div
            ref={railRef}
            className="relative flex flex-col shrink-0 border rounded bg-surface-primary overflow-hidden"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: desiredSize ?? DEFAULT_WIDTH_PX, minWidth: 'min-content', maxWidth: '40%' }}
            data-attr="logs-facet-rail"
        >
            <div className="flex items-center gap-1 px-2 py-1 border-b">
                <LemonInput
                    type="search"
                    size="small"
                    fullWidth
                    placeholder="Search facets…"
                    value={facetNameSearch}
                    onChange={setFacetNameSearch}
                    data-attr="logs-facet-rail-search"
                />
                {customFacetsEnabled && (
                    <TaxonomicStringPopover
                        groupType={TaxonomicFilterGroupType.LogAttributes}
                        groupTypes={ADD_FACET_GROUP_TYPES}
                        placeholder={null}
                        size="small"
                        icon={<IconPlus />}
                        tooltip="Add custom facet"
                        disabledReason={entriesLoading ? 'Custom facets are updating' : undefined}
                        data-attr="logs-facet-rail-add"
                        onChange={(value, groupType) =>
                            addCustomFacet(
                                value,
                                groupType === TaxonomicFilterGroupType.LogResourceAttributes
                                    ? 'resourceAttribute'
                                    : 'attribute'
                            )
                        }
                    />
                )}
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto p-2">
                {matchingKeys.size === 0 && facetNameSearch.trim() && (
                    <div className="px-1 text-xs text-muted">No matching facets</div>
                )}
                {groups.map(([group, facets]) => (
                    <div key={group}>
                        {facets.some((facet) => matchingKeys.has(facet.key)) && (
                            <div className="px-1 pb-1 mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted border-b border-primary">
                                {group}
                            </div>
                        )}
                        {facets.map((facet) => (
                            <RailFacet key={facet.key} id={id} facet={facet} hidden={!matchingKeys.has(facet.key)} />
                        ))}
                    </div>
                ))}
            </div>
            <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded my-1" />
        </div>
    )
}
