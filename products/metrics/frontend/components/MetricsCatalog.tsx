import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'

import { metricNamePickerLogic } from './metricNamePickerLogic'
import { MetricCatalogItem, metricsCatalogLogic } from './metricsCatalogLogic'

// A metric's OTel type says how to read it before it is opened. The one-liner is
// the catalog's main teaching surface: it turns a bare name into a sentence the
// reader can scan, and it matches the recommended aggregation the viewer applies.
const describeMetric = (item: MetricCatalogItem, unit?: string): string => {
    const unitLabel = unit ? ` (${unit})` : ''
    switch (item.metric_type) {
        case 'gauge':
            return `A current level, read at each scrape${unitLabel}.`
        case 'sum':
            return `A running total that grows over time${unitLabel}.`
        case 'histogram':
        case 'exponential_histogram':
            return `A distribution of values; chart a percentile${unitLabel}.`
        case 'summary':
            return `A distribution with precomputed percentiles${unitLabel}.`
        default:
            return `A metric${unitLabel}.`
    }
}

const typeTagLabel = (metricType: string): string =>
    metricType === 'sum' ? 'counter' : metricType === 'exponential_histogram' ? 'histogram' : metricType || 'unknown'

const CatalogCard = ({ item }: { item: MetricCatalogItem }): JSX.Element => {
    const { openMetric, loadSparkline, retrySparkline } = useActions(metricsCatalogLogic)
    const { catalogItemDetails, catalogItemDetailsFailed, catalogItemDetailsLoading, catalogItemsLoading } =
        useValues(metricsCatalogLogic)
    const cardRef = useRef<HTMLButtonElement>(null)
    const detail = catalogItemDetails[item.name]
    const failed = catalogItemDetailsFailed[item.name]
    const loading = catalogItemDetailsLoading[item.name]

    useEffect(() => {
        const card = cardRef.current
        if (!card || detail || failed || loading || catalogItemsLoading) {
            return
        }
        // Browsers without IntersectionObserver still show a useful catalog;
        // they fall back to loading the card when it mounts.
        if (!window.IntersectionObserver) {
            loadSparkline(item)
            return
        }
        const observer = new IntersectionObserver(
            ([entry]) => {
                if (entry?.isIntersecting) {
                    loadSparkline(item)
                    observer.disconnect()
                }
            },
            // Request just before the card enters view so the chart is normally
            // ready by the time a person reaches it.
            { rootMargin: '300px' }
        )
        observer.observe(card)
        return () => observer.disconnect()
    }, [catalogItemsLoading, detail, failed, item, loadSparkline, loading])

    return (
        <div className="relative border rounded bg-bg-3000 hover:border-accent-primary focus-within:border-accent-primary transition-colors">
            <button
                ref={cardRef}
                type="button"
                onClick={() => openMetric(item)}
                data-attr={`metrics-catalog-card-${item.name}`}
                aria-label={`Open ${item.name} chart`}
                className="absolute inset-0 rounded focus:outline-none"
            />
            <div className="relative z-10 flex flex-col gap-2 p-3 text-left pointer-events-none">
                <div className="flex items-start justify-between gap-2 min-w-0">
                    <span className="font-mono text-sm truncate" title={item.name}>
                        {item.name}
                    </span>
                    <span className="pointer-events-auto" onClick={(event) => event.stopPropagation()}>
                        <Tooltip title={describeMetric(item, detail?.unit)} openOnClick>
                            <LemonTag type="muted" size="small" forceClickable tabIndex={0}>
                                {typeTagLabel(item.metric_type)}
                            </LemonTag>
                        </Tooltip>
                    </span>
                </div>
                <div className="h-10 w-full">
                    {detail?.sparkline && detail.sparkline.length > 1 ? (
                        <Sparkline data={detail.sparkline} type="line" className="w-full h-full" />
                    ) : loading || (!detail && !failed) ? (
                        <LemonSkeleton className="h-full" />
                    ) : failed ? (
                        <div className="h-full flex items-center text-xs text-muted">Could not load recent data</div>
                    ) : (
                        <div className="h-full flex items-center text-xs text-muted">No recent data to draw</div>
                    )}
                </div>
                {detail?.last_seen && (
                    <span className="text-xs text-muted">
                        Last seen <TZLabel time={detail.last_seen} />
                    </span>
                )}
            </div>
            {failed && (
                <div className="relative z-10 px-3 pb-3">
                    <LemonButton size="xsmall" type="secondary" onClick={() => retrySparkline(item)}>
                        Retry
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

export const MetricsCatalog = (): JSX.Element => {
    // The catalog reads the picker's service scope, so mounting the picker keeps the
    // scope the overview/viewer set live and the cards consistent with the viewer.
    useMountedLogic(metricNamePickerLogic)
    const logic = useMountedLogic(metricsCatalogLogic)
    const { visibleItems, catalogItemsLoading, search } = useValues(logic)
    const { setSearch } = useActions(logic)

    return (
        <div className="@container flex flex-col gap-3 overflow-y-auto">
            <div className="flex justify-end">
                <LemonInput
                    size="small"
                    prefix={<IconSearch />}
                    value={search}
                    onChange={setSearch}
                    placeholder="Filter metrics"
                    data-attr="metrics-catalog-search"
                    className="w-64"
                />
            </div>
            {catalogItemsLoading && visibleItems.length === 0 ? (
                <div className="grid grid-cols-1 @xl:grid-cols-2 @4xl:grid-cols-3 @6xl:grid-cols-4 gap-3">
                    {Array.from({ length: 8 }).map((_, i) => (
                        <LemonSkeleton key={i} className="h-32" />
                    ))}
                </div>
            ) : visibleItems.length === 0 ? (
                <div className="border rounded p-6 text-center text-secondary">
                    {search ? `No metrics match "${search}".` : 'No metrics reported in the current scope yet.'}
                </div>
            ) : (
                <div className="grid grid-cols-1 @xl:grid-cols-2 @4xl:grid-cols-3 @6xl:grid-cols-4 gap-3">
                    {visibleItems.map((item) => (
                        <CatalogCard key={item.name} item={item} />
                    ))}
                </div>
            )}
        </div>
    )
}
