import { CSSProperties, useMemo } from 'react'
import { List } from 'react-window'

import { IconShare } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils/numbers'

import { NO_SERVICE_LABEL, ServiceRow } from './logsServicesLogic'
import { copyServiceDeepLink, serviceViewerUrl } from './serviceViewerUrl'

const ROW_HEIGHT = 30
// The scroller needs an explicit pixel height, so these have to match the `h-6` and
// `h-7` classes that actually size the subtitle and the header.
const SUBTITLE_HEIGHT = 24
const HEADER_HEIGHT = 28

/** Shared by the header and every row so the columns line up either side of the scroller. */
const COLUMN_TEMPLATE = 'grid grid-cols-[minmax(0,1fr)_6rem_5rem_12rem] items-center gap-2'

interface ServicesListProps {
    services: ServiceRow[]
    loading: boolean
    /** Both the empty state and the subtitle read differently for a search result than for the whole project. */
    searchTerm: string
}

/**
 * Every service in the project, in one scroller. The aggregates query costs the same whether
 * it returns 25 rows or all of them, because the LIMIT lands after the GROUP BY.
 */
export function ServicesList({ services, loading, searchTerm }: ServicesListProps): JSX.Element {
    const rowProps = useMemo(() => ({ services }), [services])

    if (loading && services.length === 0) {
        return (
            <div className="flex items-center justify-center p-4">
                <Spinner />
            </div>
        )
    }

    if (services.length === 0) {
        return (
            <div className="p-4 text-center text-muted">
                {searchTerm ? 'No services match your search' : 'No services found in this time range'}
            </div>
        )
    }

    return (
        <AutoSizer
            renderProp={({ width, height }: SizeProps) => {
                if (!width || !height) {
                    return null
                }
                const listHeight = Math.max(ROW_HEIGHT, height - HEADER_HEIGHT - SUBTITLE_HEIGHT)
                return (
                    <div
                        className={cn('flex flex-col', loading && 'opacity-60 transition-opacity')}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width }}
                    >
                        <div className="h-6 shrink-0 text-xs text-muted px-2">
                            {densitySubtitle(services.length, screenCount(services.length, listHeight), !!searchTerm)}
                        </div>
                        <ServicesListHeader />
                        <List<ServicesListRowProps>
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width, height: listHeight }}
                            rowCount={services.length}
                            rowHeight={ROW_HEIGHT}
                            overscanCount={5}
                            rowComponent={ServicesListRow}
                            rowProps={rowProps}
                        />
                    </div>
                )
            }}
        />
    )
}

function screenCount(serviceCount: number, listHeight: number): number {
    const rowsPerScreen = Math.max(1, Math.floor(listHeight / ROW_HEIGHT))
    return Math.ceil(serviceCount / rowsPerScreen)
}

function densitySubtitle(serviceCount: number, screens: number, searching: boolean): string {
    const noun = serviceCount === 1 ? 'service' : 'services'
    const label = `${humanFriendlyNumber(serviceCount)} ${searching ? 'matching ' : ''}${noun}`
    return screens <= 1 ? label : `${label}, about ${humanFriendlyNumber(screens)} screens`
}

function ServicesListHeader(): JSX.Element {
    return (
        <div className="h-7 shrink-0 flex items-center gap-2 pr-2 border-b text-xs font-semibold text-secondary uppercase tracking-wide">
            <div className={cn(COLUMN_TEMPLATE, 'flex-1 min-w-0 pl-2')}>
                <span>Service</span>
                <span className="text-right">Log volume</span>
                <span className="text-right">Error rate</span>
                <span>Rules</span>
            </div>
            {/* Matches the share button, which has no column title of its own. */}
            <span className="w-6 shrink-0" />
        </div>
    )
}

interface ServicesListRowProps {
    services: ServiceRow[]
}

function ServicesListRow({
    ariaAttributes,
    index,
    style,
    services,
}: {
    ariaAttributes: { 'aria-posinset': number; 'aria-setsize': number; role: 'listitem' }
    index: number
    style: CSSProperties
} & ServicesListRowProps): JSX.Element {
    const service = services[index]
    // The placeholder rows stand for logs that carry no service name at all. `parseTagsFilter`
    // drops the empty value they map back to, so a link would open the viewer unfiltered.
    const deepLinkable = service.service_name !== NO_SERVICE_LABEL
    const cells = (
        <>
            <span className="truncate font-medium">{service.service_name}</span>
            <span className="text-right tabular-nums">{humanFriendlyLargeNumber(service.log_count)}</span>
            <span className="text-right">
                <ErrorRateTag errorRate={service.error_rate} />
            </span>
            <ServiceRulesSummary rules={service.active_rules ?? []} />
        </>
    )
    const cellsClassName = cn(COLUMN_TEMPLATE, 'flex-1 min-w-0 h-full pl-2')
    return (
        <div
            {...ariaAttributes}
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
            className="flex items-center gap-2 pr-2 border-b hover:bg-accent-highlight-secondary"
            data-attr="logs-services-row"
        >
            {deepLinkable ? (
                /* The link carries the row's left padding so clicking anywhere but the share cell navigates. */
                <Link subtle to={serviceViewerUrl(service.service_name)} className={cellsClassName}>
                    {cells}
                </Link>
            ) : (
                <Tooltip title="These logs have no service name, so the viewer can't filter to them">
                    <div className={cellsClassName}>{cells}</div>
                </Tooltip>
            )}
            {deepLinkable ? (
                <Tooltip title="Copy a link to the viewer filtered to this service">
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconShare />}
                        onClick={() => copyServiceDeepLink(service.service_name)}
                        data-attr="logs-services-row-share"
                    />
                </Tooltip>
            ) : (
                /* Holds the share button's width so the columns line up across every row. */
                <span className="w-6 shrink-0" />
            )}
        </div>
    )
}

function ErrorRateTag({ errorRate }: { errorRate: number }): JSX.Element {
    const type = errorRate > 0.1 ? 'danger' : errorRate > 0.01 ? 'warning' : 'success'
    return <LemonTag type={type}>{(errorRate * 100).toFixed(1)}%</LemonTag>
}

function ServiceRulesSummary({ rules }: { rules: NonNullable<ServiceRow['active_rules']> }): JSX.Element {
    if (rules.length === 0) {
        return <span className="text-muted">-</span>
    }
    const [first, ...rest] = rules
    return (
        <Tooltip title={rules.map((rule) => rule.rule_name).join(', ')}>
            <span className="flex items-center gap-1 min-w-0 cursor-default">
                <span className="truncate">{first.rule_name}</span>
                {rest.length > 0 && <span className="shrink-0 text-muted">+{rest.length}</span>}
            </span>
        </Tooltip>
    )
}
