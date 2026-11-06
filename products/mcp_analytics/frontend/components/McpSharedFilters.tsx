import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconRefresh, IconX } from '@posthog/icons'
import { Button } from '@posthog/quill-primitives'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { MCP_TOOL_CALL_EVENT } from 'lib/components/TaxonomicFilter/utils/mcpProperties'
import { cn } from 'lib/utils/css-classes'

import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { McpInternalUsersFilter } from './McpInternalUsersFilter'

const TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.MCPProperties,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
]

// PropertyFilters always renders its add button as a raised LemonButton. These overrides restyle it as a quill
// outline button at the default size, so it matches the other buttons in the row. The values copy the outline
// variant and default size in quill's button.css. They read quill tokens such as --foreground and --radius-sm,
// which exist only inside a data-quill subtree, so the button must render inside one. LemonButton draws its
// border on both ::before and ::after of the chrome element. The quill border color is translucent, so two
// layers make it darker, and the overrides hide the ::before layer.
const QUILL_OUTLINE_ADD_FILTER_BUTTON = [
    '*:before:hidden!',
    '[--lemon-button-chrome-depth:0px]! [--lemon-button-hover-depth:0px]! [--lemon-button-press-depth:0px]! [--lemon-button-frame-bg-color:transparent]!',
    '[--button-border-color:color-mix(in_oklab,var(--foreground)_10%,transparent)]! [--lemon-button-border-color-hover:color-mix(in_oklab,var(--foreground)_10%,transparent)]!',
    'dark:[--button-border-color:color-mix(in_oklab,var(--foreground)_15%,transparent)]! dark:[--lemon-button-border-color-hover:color-mix(in_oklab,var(--foreground)_15%,transparent)]!',
    '[--lemon-button-bg-color:color-mix(in_oklab,var(--muted)_30%,transparent)]! hover:[--lemon-button-bg-color:var(--fill-hover)]!',
    '[--lemon-button-radius:var(--radius-sm)]!',
    '[--lemon-button-height:1.75rem]! [--lemon-button-font-size:0.8125rem]! [--lemon-button-icon-size:0.875rem]! [--lemon-button-padding-vertical:0.125rem]! [--lemon-button-padding-horizontal:0.5rem]! [--lemon-button-padding-adjacent-icon:0.375rem]! [--lemon-button-gap:0.5rem]!',
].join(' ')

interface McpSharedFiltersProps {
    pageKey: string
    dataAttrPrefix: string
    className?: string
    children?: ReactNode
    onRefresh: () => void
    refreshing: boolean
}

export function McpSharedFilters({
    pageKey,
    dataAttrPrefix,
    className,
    children,
    onRefresh,
    refreshing,
}: McpSharedFiltersProps): JSX.Element {
    const { propertyFilters } = useValues(mcpAnalyticsFiltersLogic)
    const { setPropertyFilters } = useActions(mcpAnalyticsFiltersLogic)

    return (
        <div className={cn('w-full min-w-0', className)} data-attr={`${dataAttrPrefix}-property-filter`}>
            <PropertyFilters
                pageKey={pageKey}
                propertyFilters={propertyFilters}
                onChange={setPropertyFilters}
                taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES}
                eventNames={[MCP_TOOL_CALL_EVENT]}
                buttonText="Add filter"
                buttonClassName={QUILL_OUTLINE_ADD_FILTER_BUTTON}
                buttonSize="small"
                renderControls={({ addFilter, activeFilters, clearFilters }) => (
                    <div className="flex w-full min-w-0 flex-col gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                            {children}
                            <div data-quill className="contents">
                                {addFilter}
                            </div>
                            {activeFilters.length > 0 && (
                                <Button
                                    variant="outline"
                                    size="icon"
                                    aria-label="Clear property filters"
                                    tooltip="Clear property filters"
                                    onClick={clearFilters}
                                    data-attr={`${dataAttrPrefix}-clear-filters`}
                                >
                                    <IconX />
                                </Button>
                            )}
                            <McpInternalUsersFilter dataAttr={`${dataAttrPrefix}-test-account-filter`} />
                            <Button
                                variant="outline"
                                size="icon"
                                aria-label="Refresh"
                                tooltip="Refresh data"
                                onClick={onRefresh}
                                loading={refreshing}
                                data-attr={`${dataAttrPrefix}-refresh`}
                            >
                                <IconRefresh />
                            </Button>
                        </div>
                        {activeFilters.length > 0 && (
                            <div className="flex min-w-0 flex-wrap items-center gap-2">{activeFilters}</div>
                        )}
                    </div>
                )}
            />
        </div>
    )
}
