import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import {
    IconClock,
    IconFilter,
    IconMinusSquare,
    IconPin,
    IconPinFilled,
    IconPlusSquare,
    IconRefresh,
} from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
    LemonTag,
    LemonTagType,
    SpinnerOverlay,
} from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel, TZLabelProps } from 'lib/components/TZLabel'
import { ListHog } from 'lib/components/hedgehogs'
import { cn } from 'lib/utils/css-classes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { LogMessage, ProductKey } from '~/queries/schema/schema-general'
import { PropertyOperator } from '~/types'

import { LogsTableRowActions } from 'products/logs/frontend/components/LogsTable/LogsTableRowActions'
import { LogsFilterGroup } from 'products/logs/frontend/components/filters/LogsFilters/FilterGroup'

import { AttributeBreakdowns } from './AttributeBreakdowns'
import { DateRangeFilter } from './filters/DateRangeFilter'
import { ServiceFilter } from './filters/ServiceFilter'
import { SeverityLevelsFilter } from './filters/SeverityLevelsFilter'
import { logsLogic } from './logsLogic'
import { ParsedLogMessage } from './types'

export const scene: SceneExport = {
    component: LogsScene,
}

export function LogsScene(): JSX.Element {
    const {
        wrapBody,
        prettifyJson,
        pinnedParsedLogs,
        parsedLogs,
        sparklineData,
        logsLoading,
        sparklineLoading,
        timestampFormat,
        isPinned,
    } = useValues(logsLogic)
    const { runQuery, setDateRangeFromSparkline } = useActions(logsLogic)

    useEffect(() => {
        runQuery()
    }, [runQuery])

    const onSelectionChange = (selection: { startIndex: number; endIndex: number }): void => {
        setDateRangeFromSparkline(selection.startIndex, selection.endIndex)
    }

    const tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime'> =
        timestampFormat === 'absolute'
            ? {
                  formatDate: 'YYYY-MM-DD',
                  formatTime: 'HH:mm:ss',
              }
            : {}

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
                    Logs is in alpha and things will change as we figure out what works. Right now you have 7-day
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
            <SceneDivider />
            <Filters />
            <div className="relative h-40 flex flex-col">
                {sparklineData.data.length > 0 ? (
                    <Sparkline
                        labels={sparklineData.labels}
                        data={sparklineData.data}
                        className="w-full flex-1"
                        onSelectionChange={onSelectionChange}
                    />
                ) : !sparklineLoading ? (
                    <div className="flex-1 text-muted flex items-center justify-center">
                        No results matching filters
                    </div>
                ) : null}
                {sparklineLoading && <SpinnerOverlay />}
            </div>
            <SceneDivider />
            <div>
                <div className="sticky top-[calc(var(--breadcrumbs-height-compact)+var(--scene-title-section-height))] z-20 bg-primary pt-2">
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
                </div>
            </div>
        </SceneContent>
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
    const { togglePinLog } = useActions(logsLogic)

    return (
        <LemonTable
            hideScrollbar
            showHeader={showHeader}
            dataSource={dataSource}
            loading={loading}
            size="small"
            embedded
            rowClassName={(record) =>
                isPinned(record.uuid) ? cn('bg-primary-highlight', showPinnedWithOpacity && 'opacity-50') : 'group'
            }
            columns={[
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
                    render: (_, { timestamp }) => <TZLabel time={timestamp} {...tzLabelFormat} />,
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
                                <pre className={cn('text-xs', wrapBody ? '' : 'whitespace-nowrap')}>
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
            }}
        />
    )
}

const ExpandedLog = ({ log }: { log: LogMessage }): JSX.Element => {
    const { expandedAttributeBreaksdowns } = useValues(logsLogic)
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
                expandedRowRender: (record) => <AttributeBreakdowns attribute={record.key} addFilter={addFilter} />,
            }}
        />
    )
}

const LogTag = ({ level }: { level: LogMessage['severity_text'] }): JSX.Element => {
    const type =
        (
            {
                debug: 'muted',
                info: 'default',
                warn: 'warning',
                error: 'danger',
                fatal: 'danger',
            } as Record<LogMessage['severity_text'], LemonTagType>
        )[level] ?? 'muted'

    return <LemonTag type={type}>{level}</LemonTag>
}

const Filters = (): JSX.Element => {
    const { logsLoading } = useValues(logsLogic)
    const { runQuery, zoomDateRange } = useActions(logsLogic)

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
                        loading={logsLoading}
                    >
                        {logsLoading ? 'Loading...' : 'Search'}
                    </LemonButton>
                </div>
            </div>
            <LogsFilterGroup />
        </div>
    )
}

const DisplayOptions = (): JSX.Element => {
    const { orderBy, wrapBody, prettifyJson, timestampFormat } = useValues(logsLogic)
    const { setOrderBy, setWrapBody, setPrettifyJson, setTimestampFormat } = useActions(logsLogic)

    return (
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
            <LemonSelect
                value={timestampFormat}
                icon={<IconClock />}
                onChange={(value) => setTimestampFormat(value)}
                size="small"
                type="secondary"
                options={[
                    { value: 'absolute', label: 'Absolute' },
                    { value: 'relative', label: 'Relative' },
                ]}
            />
        </div>
    )
}
