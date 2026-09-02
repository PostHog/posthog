import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import {
    Button,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill-primitives'

import { useChartTheme } from 'lib/charts/hooks'

import { ClusterListRow } from './ClusterListRow'
import { ClusterSortKey, mcpClusteringLogic } from './mcpClusteringLogic'
import { PRIMARY_SERIES, seriesColor } from './seriesColors'

const SORT_OPTIONS: { value: ClusterSortKey; label: string }[] = [
    { value: 'calls', label: 'Most calls' },
    { value: 'errors', label: 'Worst error rate' },
    { value: 'entropy', label: 'Most spread out' },
    { value: 'concentration', label: 'Least focused' },
]

export function ClusterListPanel(): JSX.Element {
    const {
        filteredClusters,
        selectedClusterId,
        sortKey,
        toolSearch,
        clusterFilter,
        selectedCategories,
        totalClusterCount,
        clusters,
    } = useValues(mcpClusteringLogic)
    const { selectCluster, setSortKey, setToolSearch, setClusterFilter, setSelectedCategories } =
        useActions(mcpClusteringLogic)
    // Resolved once here: the row component renders per cluster and the theme hook is not free.
    const theme = useChartTheme()
    const barColor = seriesColor(theme, PRIMARY_SERIES)

    // The category scope narrows this list too, so the count has to include it — otherwise
    // "3 of 30 shown" sits next to a Clear button that only restores some of the 30.
    const isNarrowed = clusterFilter !== 'all' || toolSearch.trim() !== '' || selectedCategories.length > 0

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden rounded border border-primary bg-surface-primary">
            <div className="shrink-0 flex flex-col gap-2 border-b border-primary p-2" data-quill>
                <div className="flex items-center gap-2">
                    <InputGroup className="flex-1">
                        <InputGroupAddon align="inline-start">
                            <InputGroupText>
                                <IconSearch />
                            </InputGroupText>
                        </InputGroupAddon>
                        <InputGroupInput
                            type="search"
                            placeholder="Filter by tool name"
                            value={toolSearch}
                            onChange={(e) => setToolSearch(e.target.value)}
                        />
                    </InputGroup>
                    <Select value={sortKey} onValueChange={(value) => setSortKey(value as ClusterSortKey)}>
                        <SelectTrigger data-attr="mcp-clustering-sort">
                            <SelectValue>
                                {(value: ClusterSortKey) => SORT_OPTIONS.find((o) => o.value === value)?.label ?? value}
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {SORT_OPTIONS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                <div className="flex items-center justify-between gap-2 text-xs text-muted">
                    <span>
                        {isNarrowed
                            ? `${filteredClusters.length} of ${clusters.length} shown`
                            : totalClusterCount > clusters.length
                              ? `Top ${clusters.length} of ${totalClusterCount} by call volume`
                              : `${clusters.length} intent group${clusters.length === 1 ? '' : 's'}`}
                    </span>
                    {isNarrowed ? (
                        <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                                setClusterFilter('all')
                                setToolSearch('')
                                setSelectedCategories([])
                            }}
                            data-attr="mcp-clustering-clear-filters"
                        >
                            Clear
                        </Button>
                    ) : null}
                </div>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto" data-attr="mcp-clustering-list">
                {filteredClusters.length === 0 ? (
                    <div className="p-4 text-center text-sm text-secondary">No intent groups match these filters.</div>
                ) : (
                    <ul className="flex flex-col list-none pl-0 m-0 divide-y divide-primary">
                        {filteredClusters.map((cluster) => (
                            <li key={cluster.id}>
                                <ClusterListRow
                                    cluster={cluster}
                                    isActive={cluster.id === selectedClusterId}
                                    onSelect={selectCluster}
                                    barColor={barColor}
                                />
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </div>
    )
}
