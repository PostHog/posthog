import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconExternal } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuTrigger,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { urls } from 'scenes/urls'

import { QuillSearchNotice } from './QuillSearchNotice'
import { SearchBreakdown, SearchChannel, SearchMetrics } from './searchPerformance'
import { SearchPerformanceDetail } from './SearchPerformanceDetail'
import { searchPerformanceLogic, SearchSourceNotice } from './searchPerformanceLogic'
import { SearchPerformanceTable } from './SearchPerformanceTable'
import { SearchSourceSuggestions } from './SearchSourceSuggestions'

export function QuillSearchPerformanceTab({
    loading,
    showSourceSuggestions,
    sourceSetupPanel,
    sourceInfoNotices,
    showSearchCard,
    breakdownOptions,
    channelOptions,
    searchPlaceholder,
    notReadyMessage,
    emptyMessage,
    footnote,
}: {
    loading: boolean
    showSourceSuggestions: boolean
    sourceSetupPanel: React.ReactNode
    sourceInfoNotices: SearchSourceNotice[]
    showSearchCard: boolean
    breakdownOptions: { value: SearchBreakdown; label: string }[]
    channelOptions: { value: SearchChannel; label: string }[]
    searchPlaceholder: string
    notReadyMessage: string
    emptyMessage: string
    footnote: React.ReactNode
}): JSX.Element {
    const {
        dataWarehouseSources,
        dataWarehouseSourcesLoading,
        sourcesError,
        sources,
        allSearchSources,
        readySources,
        displayMetrics,
        wrapText,
        conversionsDisabledReason,
        search,
        query,
        breakdown,
        channel,
        hasActiveFilters,
    } = useValues(searchPerformanceLogic)
    const { loadSources, setMetrics, setSearch, setBreakdown, setChannel, selectRow, clearFilters, setWrapText } =
        useActions(searchPerformanceLogic)

    const emptyState = useMemo(
        () => (
            <>
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    {emptyMessage}
                </Text>
                {hasActiveFilters && (
                    <Button variant="outline" onClick={clearFilters}>
                        Clear filters
                    </Button>
                )}
            </>
        ),
        [emptyMessage, hasActiveFilters, clearFilters]
    )

    return (
        <div className="@container flex flex-col gap-4 pb-8" data-attr="marketing-search-performance">
            {loading ? (
                <div className="flex flex-col gap-2">
                    {Array.from({ length: 5 }, (_, index) => (
                        <Skeleton key={index} className="h-10" />
                    ))}
                </div>
            ) : sourcesError && !dataWarehouseSources ? (
                <QuillSearchNotice
                    tone="destructive"
                    action={
                        <Button variant="outline" onClick={loadSources} loading={dataWarehouseSourcesLoading}>
                            Try again
                        </Button>
                    }
                >
                    Could not load your search sources. Try again to view search performance.
                </QuillSearchNotice>
            ) : (
                <>
                    {showSourceSuggestions && !hasActiveFilters && <SearchSourceSuggestions />}
                    {sourceSetupPanel}
                    {sourceInfoNotices.map(({ sourceId, name, message }) => (
                        <QuillSearchNotice
                            key={sourceId}
                            action={
                                <Button
                                    variant="outline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive
                                            to={urls.dataWarehouseSource(`managed-${sourceId}`)}
                                            target="_blank"
                                        />
                                    }
                                    data-attr="marketing-search-manage-source"
                                >
                                    Manage source
                                    <IconExternal />
                                </Button>
                            }
                        >
                            {`${name}: ${message}`}
                        </QuillSearchNotice>
                    ))}
                    {sources.length === 0 && (hasActiveFilters || allSearchSources.length > 0) && (
                        <QuillSearchNotice
                            action={
                                <Button variant="outline" onClick={clearFilters}>
                                    Clear filters
                                </Button>
                            }
                        >
                            No search data matches your filters. Clear the filters to see all connected search sources.
                        </QuillSearchNotice>
                    )}
                    {showSearchCard && (
                        <div className="flex flex-col gap-2">
                            <div className="flex flex-wrap items-center gap-2">
                                {readySources.length > 0 && (
                                    <AnalyticsSearchInput
                                        value={search}
                                        onChange={setSearch}
                                        label={searchPlaceholder}
                                        placeholder={searchPlaceholder}
                                        dataAttr="marketing-search-keyword-filter"
                                    />
                                )}
                                <Select<SearchBreakdown>
                                    value={breakdown}
                                    onValueChange={(next) => next !== null && setBreakdown(next)}
                                >
                                    <SelectTrigger aria-label="Breakdown" data-attr="marketing-search-breakdown">
                                        <SelectValue>
                                            {(selected: SearchBreakdown | null) =>
                                                breakdownOptions.find((option) => option.value === selected)?.label
                                            }
                                        </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                        {breakdownOptions.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                                <Select<SearchChannel>
                                    value={channel}
                                    onValueChange={(next) => next !== null && setChannel(next)}
                                >
                                    <SelectTrigger aria-label="Channel">
                                        <SelectValue>
                                            {(selected: SearchChannel | null) =>
                                                channelOptions.find((option) => option.value === selected)?.label
                                            }
                                        </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                        {channelOptions.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                                {readySources.length > 0 && (
                                    <>
                                        <div className="flex-1" />
                                        <div className="flex flex-wrap items-center gap-2">
                                            <ToggleGroup
                                                variant="outline"
                                                aria-label="Columns"
                                                value={[displayMetrics]}
                                                onValueChange={(next: string[]) => {
                                                    const picked = next[0] as SearchMetrics | undefined
                                                    if (picked) {
                                                        setMetrics(picked)
                                                    }
                                                }}
                                                data-attr="marketing-search-column-view"
                                            >
                                                <ToggleGroupItem value="traffic">Traffic</ToggleGroupItem>
                                                <ToggleGroupItem
                                                    value="conversions"
                                                    disabledReason={conversionsDisabledReason ?? undefined}
                                                >
                                                    Conversions
                                                </ToggleGroupItem>
                                            </ToggleGroup>
                                            <DropdownMenu>
                                                <DropdownMenuTrigger
                                                    render={
                                                        <Button
                                                            variant="outline"
                                                            data-attr="marketing-search-table-options"
                                                        />
                                                    }
                                                >
                                                    Table options
                                                </DropdownMenuTrigger>
                                                <DropdownMenuContent align="end">
                                                    <DropdownMenuCheckboxItem
                                                        checked={wrapText}
                                                        onCheckedChange={(checked) => setWrapText(checked)}
                                                        closeOnClick={false}
                                                    >
                                                        Wrap text
                                                    </DropdownMenuCheckboxItem>
                                                </DropdownMenuContent>
                                            </DropdownMenu>
                                        </div>
                                    </>
                                )}
                            </div>
                            {readySources.length === 0 && sources.length > 0 && (
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    {notReadyMessage}
                                </Text>
                            )}
                            {readySources.length > 0 && (
                                <SearchPerformanceTable
                                    query={query}
                                    metrics={displayMetrics}
                                    wrapText={wrapText}
                                    onSelect={selectRow}
                                    embedded
                                    emptyState={emptyState}
                                />
                            )}
                        </div>
                    )}
                    {readySources.length > 0 && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {footnote}
                        </Text>
                    )}
                </>
            )}
            <SearchPerformanceDetail />
        </div>
    )
}
