import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconFilter, IconMinusSquare, IconPin, IconPinFilled, IconPlusSquare, IconRefresh } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
    Tooltip,
} from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel, TZLabelProps } from 'lib/components/TZLabel'
import { ListHog } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { IconPauseCircle, IconPlayCircle } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { LogMessage, ProductKey } from '~/queries/schema/schema-general'
import { PropertyOperator } from '~/types'

import { LogTag } from 'products/logs/frontend/components/LogTag'
import { LogsSparkline } from 'products/logs/frontend/components/LogsSparkline'
import { LogsTableRowActions } from 'products/logs/frontend/components/LogsTable/LogsTableRowActions'
import { VirtualizedLogsList } from 'products/logs/frontend/components/VirtualizedLogsList'
import { LogsFilterGroup } from 'products/logs/frontend/components/filters/LogsFilters/FilterGroup'

import { AttributeBreakdowns } from './AttributeBreakdowns'
import { DateRangeFilter } from './filters/DateRangeFilter'
import { ServiceFilter } from './filters/ServiceFilter'
import { SeverityLevelsFilter } from './filters/SeverityLevelsFilter'
import { logsLogic } from './logsLogic'
import { ParsedLogMessage } from './types'

export const scene: SceneExport = {
    component: LogsScene,
    logic: logsLogic,
    settingSectionId: 'product-logs',
}

export function LogsScene(): JSX.Element {
    const { logsLoading } = useValues(logsLogic)
    const { runQuery, highlightNextLog, highlightPreviousLog, toggleExpandLog } = useActions(logsLogic)
    const { highlightedLogId: sceneHighlightedLogId } = useValues(logsLogic)

    useEffect(() => {
        runQuery()
    }, [runQuery])

    useKeyboardHotkeys(
        {
            arrowdown: { action: highlightNextLog },
            j: { action: highlightNextLog },
            arrowup: { action: highlightPreviousLog },
            k: { action: highlightPreviousLog },
            enter: {
                action: () => {
                    if (sceneHighlightedLogId) {
                        toggleExpandLog(sceneHighlightedLogId)
                    }
                },
            },
            r: { action: () => !logsLoading && runQuery() },
        },
        [sceneHighlightedLogId, logsLoading, runQuery]
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Logs].name}
                description={sceneConfigurations[Scene.Logs].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Logs].iconType || 'default_icon_type',
                }}
            />
            <LemonBanner
                type="warning"
                dismissKey="logs-beta-banner"
                action={{ children: 'Send feedback', id: 'logs-feedback-button' }}
            >
                <p>
                    Logs is in beta and things will change as we figure out what works. Right now you have 7-day
                    retention with ingestion rate limits. Tell us what you need, what's broken, or if you're hitting
                    limits, we want to hear from you.
                </p>
            </LemonBanner>
            <ProductIntroduction
                productName="logs"
                productKey={ProductKey.LOGS}
                thingName="log"
                description={sceneConfigurations[Scene.Logs].description ?? ''}
                docsURL="https://posthog.com/docs/logs"
                customHog={ListHog}
                isEmpty={false}
            />
            <Filters />
            <LogsSparkline />
            <SceneDivider />
            <LogsListContainer />
        </SceneContent>
    )
}

const LogsListContainer = (): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const useVirtualizedList = !!featureFlags[FEATURE_FLAGS.LOGS_VIRTUALIZED_LIST]
    return useVirtualizedList ? <VirtualizedLogsListLogs /> : <LemonTableLogs />
}

const LemonTableLogs = (): JSX.Element => {
    const {
        wrapBody,
        prettifyJson,
        pinnedParsedLogs,
        parsedLogs,
        logsLoading,
        isPinned,
        hasMoreLogsToLoad,
        logsPageSize,
        logsRemainingToLoad,
    } = useValues(logsLogic)

    const { fetchNextLogsPage } = useActions(logsLogic)

    const tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime'> = {
        formatDate: 'YYYY-MM-DD',
        formatTime: 'HH:mm:ss.SSS',
    }

    return (
        <div>
            <div className="sticky top-[calc(var(--breadcrumbs-height-compact)+var(--scene-title-section-height)-3px)] z-20 bg-primary pt-2">
                <div className="pb-2">
                    <DisplayOptions />
                </div>
                {pinnedParsedLogs.length > 0 && (
                    <div className="border rounded-t bg-bg-light shadow-sm">
                        <LogsTable
                            dataSource={pinnedParsedLogs}
                            loading={false}
                            isPinned={isPinned}
                            wrapBody={wrapBody}
                            prettifyJson={prettifyJson}
                            tzLabelFormat={tzLabelFormat}
                        />
                    </div>
                )}
            </div>
            <div className={cn('flex-1 border bg-bg-light', pinnedParsedLogs.length > 0 ? 'rounded-b' : 'rounded')}>
                <LogsTable
                    showHeader={!pinnedParsedLogs.length}
                    dataSource={parsedLogs}
                    loading={logsLoading}
                    isPinned={isPinned}
                    wrapBody={wrapBody}
                    prettifyJson={prettifyJson}
                    tzLabelFormat={tzLabelFormat}
                    showPinnedWithOpacity
                />
                {parsedLogs.length > 0 && (
                    <div className="m-2 flex items-center">
                        <LemonButton
                            onClick={() => fetchNextLogsPage()}
                            loading={logsLoading}
                            fullWidth
                            center
                            disabled={!hasMoreLogsToLoad || logsLoading}
                        >
                            {logsLoading
                                ? 'Loading more logs...'
                                : hasMoreLogsToLoad
                                  ? `Click to load ${humanFriendlyNumber(Math.min(logsPageSize, logsRemainingToLoad))} more`
                                  : `Showing all ${humanFriendlyNumber(parsedLogs.length)} logs`}
                        </LemonButton>
                    </div>
                )}
            </div>
        </div>
    )
}

const VirtualizedLogsListLogs = (): JSX.Element => {
    const { wrapBody, prettifyJson, pinnedParsedLogs, parsedLogs, logsLoading, isPinned } = useValues(logsLogic)

    const tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime'> = {
        formatDate: 'YYYY-MM-DD',
        formatTime: 'HH:mm:ss.SSS',
    }

    return (
        <div className="flex flex-col gap-2 py-2 h-[calc(100vh_-_var(--breadcrumbs-height-compact,_0px)_-_var(--scene-title-section-height,_0px)_-_5px)]">
            <div className="sticky top-0 z-20 py-2">
                <VirtualizedLogsListDisplayOptions />
            </div>
            {pinnedParsedLogs.length > 0 && (
                <div className="border rounded-t bg-bg-light shadow-sm">
                    <VirtualizedLogsList
                        dataSource={pinnedParsedLogs}
                        loading={false}
                        isPinned={isPinned}
                        wrapBody={wrapBody}
                        prettifyJson={prettifyJson}
                        tzLabelFormat={tzLabelFormat}
                        showPinnedWithOpacity
                        fixedHeight={250}
                        disableInfiniteScroll
                    />
                </div>
            )}
            <div
                className={cn(
                    'border bg-bg-light flex-1 min-h-0',
                    pinnedParsedLogs.length > 0 ? 'rounded-b' : 'rounded'
                )}
            >
                <VirtualizedLogsList
                    dataSource={parsedLogs}
                    loading={logsLoading}
                    isPinned={isPinned}
                    wrapBody={wrapBody}
                    prettifyJson={prettifyJson}
                    tzLabelFormat={tzLabelFormat}
                    showPinnedWithOpacity
                />
            </div>
        </div>
    )
}

interface LogsTableProps {
    dataSource: ParsedLogMessage[]
    loading: boolean
    isPinned: (uuid: string) => boolean
    wrapBody: boolean
    prettifyJson: boolean
    tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime'>
    showPinnedWithOpacity?: boolean
    showHeader?: boolean
}

function LogsTable({
    dataSource,
    loading,
    isPinned,
    wrapBody,
    prettifyJson,
    tzLabelFormat,
    showPinnedWithOpacity = false,
    showHeader = true,
}: LogsTableProps): JSX.Element {
    const { togglePinLog, setHighlightedLogId, toggleExpandLog } = useActions(logsLogic)
    const { highlightedLogId, expandedLogIds } = useValues(logsLogic)
    const tableRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (!loading && highlightedLogId && tableRef.current) {
            requestAnimationFrame(() => {
                const highlightedRow = tableRef.current?.querySelector(`[data-row-key="${highlightedLogId}"]`)
                if (highlightedRow) {
                    highlightedRow.scrollIntoView({ behavior: 'smooth', block: 'center' })
                }
            })
        }
    }, [loading, highlightedLogId])

    return (
        <div ref={tableRef}>
            <LemonTable
                hideScrollbar
                showHeader={showHeader}
                dataSource={dataSource}
                loading={loading}
                size="small"
                embedded
                rowKey="uuid"
                rowStatus={(record) =>
                    record.uuid === highlightedLogId ? 'highlighted' : record.new ? 'highlight-new' : null
                }
                rowClassName={(record) =>
                    isPinned(record.uuid) ? cn('bg-primary-highlight', showPinnedWithOpacity && 'opacity-50') : 'group'
                }
                columns={[
                    {
                        title: '#',
                        key: 'row_number',
                        width: 0,
                        className: 'relative',
                        render: (_, record, index) => {
                            const isHighlighted = record.uuid === highlightedLogId
                            return (
                                <Tooltip title="Click to highlight (↑↓ or j/k to navigate, Enter to expand)">
                                    <button
                                        type="button"
                                        onClick={() => setHighlightedLogId(isHighlighted ? null : record.uuid)}
                                        className="absolute inset-0 cursor-pointer"
                                    />
                                    <span
                                        className={cn(
                                            'font-mono text-xs pointer-events-none transition-colors',
                                            isPinned(record.uuid) ? 'opacity-0' : '',
                                            isHighlighted ? 'text-primary font-semibold' : 'text-muted'
                                        )}
                                    >
                                        {index + 1}
                                    </span>
                                </Tooltip>
                            )
                        },
                    },
                    {
                        title: '',
                        key: 'actions',
                        width: 0,
                        render: (_, record) => {
                            const pinned = isPinned(record.uuid)
                            return (
                                <div className="flex items-center gap-1">
                                    <LemonButton
                                        size="xsmall"
                                        noPadding
                                        icon={pinned ? <IconPinFilled /> : <IconPin />}
                                        onClick={() => togglePinLog(record.uuid)}
                                        tooltip={pinned ? 'Unpin log' : 'Pin log'}
                                        className={cn(
                                            'transition-opacity',
                                            pinned
                                                ? 'text-primary opacity-100'
                                                : 'text-muted opacity-0 group-hover:opacity-100'
                                        )}
                                    />
                                    <LogsTableRowActions log={record} />
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Timestamp',
                        key: 'timestamp',
                        dataIndex: 'timestamp',
                        width: 180,
                        render: (_, { timestamp }) => (
                            <TZLabel time={timestamp} {...tzLabelFormat} showNow={false} showToday={false} />
                        ),
                    },
                    {
                        title: 'Level',
                        key: 'severity_text',
                        dataIndex: 'severity_text',
                        width: 100,
                        render: (_, record) => <LogTag level={record.severity_text} />,
                    },
                    {
                        title: 'Message',
                        key: 'body',
                        dataIndex: 'body',
                        render: (_, { cleanBody, parsedBody }) => {
                            if (parsedBody && prettifyJson) {
                                return (
                                    <pre className={cn('text-xs m-0', wrapBody ? '' : 'whitespace-nowrap')}>
                                        {JSON.stringify(parsedBody, null, 2)}
                                    </pre>
                                )
                            }

                            return <div className={cn(wrapBody ? '' : 'whitespace-nowrap')}>{cleanBody}</div>
                        },
                    },
                ]}
                expandable={{
                    noIndent: true,
                    expandedRowRender: (log) => <ExpandedLog log={log} />,
                    isRowExpanded: (record) => expandedLogIds.has(record.uuid),
                    onRowExpand: (record) => toggleExpandLog(record.uuid),
                    onRowCollapse: (record) => toggleExpandLog(record.uuid),
                }}
            />
        </div>
    )
}

const ExpandedLog = ({ log }: { log: LogMessage }): JSX.Element => {
    const { expandedAttributeBreaksdowns, tabId } = useValues(logsLogic)
    const { addFilter, toggleAttributeBreakdown } = useActions(logsLogic)

    const attributes = log.attributes
    const rows = Object.entries(attributes).map(([key, value]) => ({ key, value }))

    return (
        <LemonTable
            embedded
            showHeader={false}
            columns={[
                {
                    key: 'actions',
                    width: 0,
                    render: (_, record) => (
                        <div className="flex gap-x-0">
                            <LemonButton
                                tooltip="Add as filter"
                                size="xsmall"
                                onClick={() => addFilter(record.key, record.value)}
                            >
                                <IconPlusSquare />
                            </LemonButton>
                            <LemonButton
                                tooltip="Exclude as filter"
                                size="xsmall"
                                onClick={() => addFilter(record.key, record.value, PropertyOperator.IsNot)}
                            >
                                <IconMinusSquare />
                            </LemonButton>
                            <LemonButton
                                tooltip="Show breakdown"
                                size="xsmall"
                                onClick={() => toggleAttributeBreakdown(record.key)}
                            >
                                <IconFilter />
                            </LemonButton>
                        </div>
                    ),
                },
                {
                    title: 'Key',
                    key: 'key',
                    dataIndex: 'key',
                    width: 0,
                },
                {
                    title: 'Value',
                    key: 'value',
                    dataIndex: 'value',
                    render: (_, record) => (
                        <CopyToClipboardInline
                            explicitValue={String(record.value)}
                            description="attribute value"
                            iconSize="xsmall"
                            iconPosition="start"
                            selectable
                            className="gap-1"
                        >
                            {String(record.value)}
                        </CopyToClipboardInline>
                    ),
                },
            ]}
            dataSource={rows}
            expandable={{
                noIndent: true,
                showRowExpansionToggle: false,
                isRowExpanded: (record) => expandedAttributeBreaksdowns.includes(record.key),
                expandedRowRender: (record) => (
                    <AttributeBreakdowns attribute={record.key} addFilter={addFilter} tabId={tabId} />
                ),
            }}
        />
    )
}

const Filters = (): JSX.Element => {
    const { logsLoading, liveTailRunning, liveTailDisabledReason } = useValues(logsLogic)
    const { runQuery, zoomDateRange, setLiveTailRunning } = useActions(logsLogic)

    return (
        <div className="flex flex-col gap-y-1.5">
            <div className="flex justify-between gap-y-2 flex-wrap-reverse">
                <div className="flex gap-x-1 gap-y-2 flex-wrap">
                    <SeverityLevelsFilter />
                    <ServiceFilter />
                </div>
                <div className="flex gap-x-1">
                    <LemonButton
                        size="small"
                        icon={<IconMinusSquare />}
                        type="secondary"
                        onClick={() => zoomDateRange(2)}
                    />
                    <LemonButton
                        size="small"
                        icon={<IconPlusSquare />}
                        type="secondary"
                        onClick={() => zoomDateRange(0.5)}
                    />
                    <DateRangeFilter />
                    <LemonButton
                        size="small"
                        icon={<IconRefresh />}
                        type="secondary"
                        onClick={() => runQuery()}
                        loading={logsLoading || liveTailRunning}
                        disabledReason={liveTailRunning ? 'Disable live tail to manually refresh' : undefined}
                    >
                        {liveTailRunning ? 'Tailing...' : logsLoading ? 'Loading...' : 'Search'}
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type={liveTailRunning ? 'primary' : 'secondary'}
                        icon={liveTailRunning ? <IconPauseCircle /> : <IconPlayCircle />}
                        onClick={() => setLiveTailRunning(!liveTailRunning)}
                        disabledReason={liveTailRunning ? undefined : liveTailDisabledReason}
                    >
                        Live tail
                    </LemonButton>
                </div>
            </div>
            <LogsFilterGroup />
        </div>
    )
}

const DisplayOptions = (): JSX.Element => {
    const { orderBy, wrapBody, prettifyJson, logsPageSize, totalLogsMatchingFilters, parsedLogs, sparklineLoading } =
        useValues(logsLogic)
    const { setOrderBy, setWrapBody, setPrettifyJson, setLogsPageSize } = useActions(logsLogic)

    return (
        <div className="flex justify-between">
            <div className="flex gap-2">
                <LemonSegmentedButton
                    value={orderBy}
                    onChange={setOrderBy}
                    options={[
                        {
                            value: 'earliest',
                            label: 'Earliest',
                        },
                        {
                            value: 'latest',
                            label: 'Latest',
                        },
                    ]}
                    size="small"
                />
                <LemonCheckbox checked={wrapBody} bordered onChange={setWrapBody} label="Wrap message" size="small" />
                <LemonCheckbox
                    checked={prettifyJson}
                    bordered
                    onChange={setPrettifyJson}
                    label="Prettify JSON"
                    size="small"
                />
            </div>
            <div className="flex items-center gap-4">
                {!sparklineLoading && totalLogsMatchingFilters > 0 && (
                    <span className="text-muted text-xs">
                        Showing {humanFriendlyNumber(parsedLogs.length)} of{' '}
                        {humanFriendlyNumber(totalLogsMatchingFilters)} logs
                    </span>
                )}
                <LemonField.Pure label="Page size" inline className="items-center gap-2">
                    <LemonSelect
                        value={logsPageSize}
                        onChange={(value: number) => setLogsPageSize(value)}
                        size="small"
                        type="secondary"
                        options={[
                            { value: 100, label: '100' },
                            { value: 200, label: '200' },
                            { value: 500, label: '500' },
                            { value: 1000, label: '1000' },
                        ]}
                    />
                </LemonField.Pure>
                <span className="text-muted text-xs flex items-center gap-1">
                    <KeyboardShortcut arrowup />
                    <KeyboardShortcut arrowdown />
                    or
                    <KeyboardShortcut j />
                    <KeyboardShortcut k />
                    navigate
                    <span className="mx-1">·</span>
                    <KeyboardShortcut enter />
                    expand
                    <span className="mx-1">·</span>
                    <KeyboardShortcut r />
                    refresh
                </span>
            </div>
        </div>
    )
}

const VirtualizedLogsListDisplayOptions = (): JSX.Element => {
    const { orderBy, wrapBody, prettifyJson, totalLogsMatchingFilters, sparklineLoading } = useValues(logsLogic)
    const { setOrderBy, setWrapBody, setPrettifyJson } = useActions(logsLogic)

    return (
        <div className="flex justify-between">
            <div className="flex gap-2">
                <LemonSegmentedButton
                    value={orderBy}
                    onChange={setOrderBy}
                    options={[
                        {
                            value: 'earliest',
                            label: 'Earliest',
                        },
                        {
                            value: 'latest',
                            label: 'Latest',
                        },
                    ]}
                    size="small"
                />
                <LemonCheckbox checked={wrapBody} bordered onChange={setWrapBody} label="Wrap message" size="small" />
                <LemonCheckbox
                    checked={prettifyJson}
                    bordered
                    onChange={setPrettifyJson}
                    label="Prettify JSON"
                    size="small"
                />
            </div>
            <div className="flex items-center gap-4">
                {!sparklineLoading && totalLogsMatchingFilters > 0 && (
                    <span className="text-muted text-xs">{humanFriendlyNumber(totalLogsMatchingFilters)} logs</span>
                )}
                <span className="text-muted text-xs flex items-center gap-1">
                    <KeyboardShortcut arrowup />
                    <KeyboardShortcut arrowdown />
                    or
                    <KeyboardShortcut j />
                    <KeyboardShortcut k />
                    navigate
                    <span className="mx-1">·</span>
                    <KeyboardShortcut enter />
                    expand
                    <span className="mx-1">·</span>
                    <KeyboardShortcut r />
                    refresh
                </span>
            </div>
        </div>
    )
}
