import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

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
    const { catalogItemDetails, catalogItemDetailsFailed, catalogItemDetailsLoading } = useValues(metricsCatalogLogic)
    const cardRef = useRef<HTMLButtonElement>(null)
    const detail = catalogItemDetails[item.name]
    const failed = catalogItemDetailsFailed[item.name]
    const loading = catalogItemDetailsLoading[item.name]

    useEffect(() => {
        const card = cardRef.current
        if (!card || detail || failed || loading) {
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
    }, [detail, item, loadSparkline, loading])

    return (
        <div className="flex flex-col border rounded hover:border-accent-primary focus-within:border-accent-primary transition-colors bg-bg-3000">
            <button
                ref={cardRef}
                type="button"
                onClick={() => openMetric(item)}
                data-attr={`metrics-catalog-card-${item.name}`}
                className="flex flex-col gap-2 p-3 text-left"
            >
                <div className="flex items-start justify-between gap-2 min-w-0">
                    <span className="font-mono text-sm truncate" title={item.name}>
                        {item.name}
                    </span>
                    <LemonTag type="muted" size="small">
                        {typeTagLabel(item.metric_type)}
                    </LemonTag>
                </div>
                <div className="h-10 w-full">
                    {detail?.sparkline && detail.sparkline.length > 1 ? (
                        <Sparkline data={detail.sparkline} type="line" />
                    ) : loading ? (
                        <LemonSkeleton className="h-full" />
                    ) : failed ? (
                        <div className="h-full flex items-center text-xs text-muted">Could not load recent data</div>
                    ) : (
                        <div className="h-full flex items-center text-xs text-muted">No recent data to draw</div>
                    )}
                </div>
                <p className="text-xs text-secondary mb-0">{describeMetric(item, detail?.unit)}</p>
                {detail?.last_seen && (
                    <span className="text-xs text-muted">
                        Last seen <TZLabel time={detail.last_seen} />
                    </span>
                )}
            </button>
            {failed && (
                <div className="px-3 pb-3">
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
        <div className="flex flex-col gap-3 overflow-y-auto">
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <p className="text-secondary mb-0">
                    Every metric you are collecting, as a card. Click one to open its chart.
                </p>
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
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                    {Array.from({ length: 8 }).map((_, i) => (
                        <LemonSkeleton key={i} className="h-32" />
                    ))}
                </div>
            ) : visibleItems.length === 0 ? (
                <div className="border rounded p-6 text-center text-secondary">
                    {search ? `No metrics match "${search}".` : 'No metrics reported in the current scope yet.'}
                </div>
            ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                    {visibleItems.map((item) => (
                        <CatalogCard key={item.name} item={item} />
                    ))}
                </div>
            )}
        </div>
    )
}
