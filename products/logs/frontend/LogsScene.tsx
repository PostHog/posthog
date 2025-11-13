import colors from 'ansi-colors'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconClock, IconFilter, IconMinusSquare, IconPlusSquare, IconRefresh } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
    LemonTag,
    LemonTagType,
    SpinnerOverlay,
} from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel, TZLabelProps } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { LogMessage } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { AttributeBreakdowns } from './AttributeBreakdowns'
import { AttributesFilter } from './filters/AttributesFilter'
import { DateRangeFilter } from './filters/DateRangeFilter'
import { SearchTermFilter } from './filters/SearchTermFilter'
import { ServiceFilter } from './filters/ServiceFilter'
import { SeverityLevelsFilter } from './filters/SeverityLevelsFilter'
import { logsLogic } from './logsLogic'

export const scene: SceneExport = {
    component: LogsScene,
}

export function LogsScene(): JSX.Element {
    const { wrapBody, logs, sparklineData, logsLoading, sparklineLoading, timestampFormat } = useValues(logsLogic)
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
        <SceneContent className="h-screen">
            <SceneTitleSection
                name={sceneConfigurations[Scene.Logs].name}
                description={sceneConfigurations[Scene.Logs].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Logs].iconType || 'default_icon_type',
                }}
            />
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
            <DisplayOptions />
            <div className="flex-1 overflow-y-auto border rounded bg-bg-light">
                <LemonTable
                    hideScrollbar
                    dataSource={logs}
                    loading={logsLoading}
                    size="small"
                    embedded
                    columns={[
                        {
                            title: 'Timestamp',
                            key: 'timestamp',
                            dataIndex: 'timestamp',
                            width: 0,
                            render: (_, { timestamp }) => <TZLabel time={timestamp} {...tzLabelFormat} />,
                        },
                        {
                            title: 'Level',
                            key: 'severity_text',
                            dataIndex: 'severity_text',
                            width: 0,
                            render: (_, record) => <LogTag level={record.severity_text} />,
                        },
                        {
                            title: 'Message',
                            key: 'body',
                            dataIndex: 'body',
                            render: (_, { body }) => (
                                <div className={cn(wrapBody ? '' : 'whitespace-nowrap')}>{colors.unstyle(body)}</div>
                            ),
                        },
                    ]}
                    expandable={{
                        noIndent: true,
                        expandedRowRender: (log) => <ExpandedLog log={log} />,
                    }}
                />
            </div>
        </SceneContent>
    )
}

const ExpandedLog = ({ log }: { log: LogMessage }): JSX.Element => {
    const { filterGroup, expandedAttributeBreaksdowns } = useValues(logsLogic)
    const { setFilterGroup, toggleAttributeBreakdown } = useActions(logsLogic)

    const attributes = log.attributes
    const rows = Object.entries(attributes).map(([key, value]) => ({ key, value }))

    const addFilter = (key: string, value: string, operator = PropertyOperator.Exact): void => {
        const newGroup = { ...filterGroup.values[0] } as UniversalFiltersGroup

        newGroup.values.push({
            key,
            value: [value],
            operator: operator,
            type: PropertyFilterType.Log,
        })

        setFilterGroup({ ...filterGroup, values: [newGroup] }, false)
    }

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
                    <AttributesFilter />
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
            <SearchTermFilter />
        </div>
    )
}

const DisplayOptions = (): JSX.Element => {
    const { orderBy, wrapBody, timestampFormat } = useValues(logsLogic)
    const { setOrderBy, setWrapBody, setTimestampFormat } = useActions(logsLogic)

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
