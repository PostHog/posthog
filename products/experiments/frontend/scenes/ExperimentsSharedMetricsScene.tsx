import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconChevronLeft, IconChevronRight, IconCopy, IconPencil, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { pluralize } from 'lib/utils/strings'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { MetricTypeTag } from 'scenes/experiments/MetricsView/shared/MetricTypeTag'
import { openDeleteSharedMetricDialog } from 'scenes/experiments/SharedMetrics/deleteSharedMetricDialog'
import { InlineTagEditor } from 'scenes/experiments/SharedMetrics/InlineTagEditor'
import { SharedMetric } from 'scenes/experiments/SharedMetrics/sharedMetricLogic'
import { PAGE_SIZE, sharedMetricsLogic } from 'scenes/experiments/SharedMetrics/sharedMetricsLogic'
import { isLegacySharedMetric } from 'scenes/experiments/utils'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery } from '~/queries/schema/schema-general'

import { QuillExperimentsSharedMetricsScene } from './QuillExperimentsSharedMetricsScene'
import {
    LEGACY_SHARED_METRIC_DOCS_URL,
    LEGACY_SHARED_METRIC_DUPLICATE_REASON,
    LEGACY_SHARED_METRIC_HELP,
    SHARED_METRICS_EMPTY,
    SHARED_METRICS_INTRO,
} from './sharedMetricsCopy'

export const scene: SceneExport = {
    component: ExperimentsSharedMetricsScene,
    logic: sharedMetricsLogic,
}

export function ExperimentsSharedMetricsScene(): JSX.Element {
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (todayRailNav && resultsRedesign) {
        return <QuillExperimentsSharedMetricsScene />
    }
    return <LemonExperimentsSharedMetricsScene />
}

function LemonExperimentsSharedMetricsScene(): JSX.Element {
    const { sharedMetrics, sharedMetricsLoading, searchTerm, savingTagsMetricId, count, page } =
        useValues(sharedMetricsLogic)
    const { setSearchTerm, setPage, updateSharedMetricTags, deleteSharedMetric } = useActions(sharedMetricsLogic)
    const { currentProjectId } = useValues(teamLogic)
    const [deleteCheckMetricId, setDeleteCheckMetricId] = useState<number | null>(null)

    const handleDelete = async (sharedMetricId: number): Promise<void> => {
        if (deleteCheckMetricId !== null) {
            return
        }
        setDeleteCheckMetricId(sharedMetricId)
        try {
            await openDeleteSharedMetricDialog({
                projectId: currentProjectId,
                sharedMetricId,
                onDelete: () => deleteSharedMetric(sharedMetricId),
            })
        } finally {
            setDeleteCheckMetricId(null)
        }
    }

    const startCount = count === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
    const endCount = page * PAGE_SIZE < count ? page * PAGE_SIZE : count

    const columns: LemonTableColumns<SharedMetric> = [
        {
            key: 'name',
            title: 'Name',
            render: (_, sharedMetric) => {
                return (
                    <LemonTableLink
                        to={sharedMetric.id ? urls.experimentsSharedMetric(sharedMetric.id) : undefined}
                        title={
                            <>
                                {stringWithWBR(sharedMetric.name, 17)}
                                {isLegacySharedMetric(sharedMetric) && (
                                    <Tooltip title={LEGACY_SHARED_METRIC_HELP} docLink={LEGACY_SHARED_METRIC_DOCS_URL}>
                                        <LemonTag type="warning" className="ml-1">
                                            Legacy
                                        </LemonTag>
                                    </Tooltip>
                                )}
                            </>
                        }
                    />
                )
            },
        },
        {
            key: 'description',
            title: 'Description',
            dataIndex: 'description',
        },
        {
            title: 'Tags',
            dataIndex: 'tags' as keyof SharedMetric,
            render: function Render(_: any, metric: SharedMetric) {
                return (
                    <InlineTagEditor
                        metric={metric}
                        onSave={(newTags) => updateSharedMetricTags(metric.id, newTags)}
                        saving={savingTagsMetricId === metric.id}
                    />
                )
            },
        } as LemonTableColumn<SharedMetric, keyof SharedMetric | undefined>,
        {
            title: 'Type',
            key: 'type',
            render: (_, metric: SharedMetric) => (
                <MetricTypeTag
                    metric={metric.query as ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery}
                />
            ),
        },
        createdByColumn<SharedMetric>() as LemonTableColumn<SharedMetric, keyof SharedMetric | undefined>,
        createdAtColumn<SharedMetric>() as LemonTableColumn<SharedMetric, keyof SharedMetric | undefined>,
        {
            key: 'actions',
            title: '',
            width: 0,
            render: (_, sharedMetric) => {
                return (
                    <More
                        size="xsmall"
                        overlay={
                            <>
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    icon={<IconPencil />}
                                    onClick={() => {
                                        router.actions.push(urls.experimentsSharedMetric(sharedMetric.id))
                                    }}
                                >
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    icon={<IconCopy />}
                                    disabledReason={
                                        isLegacySharedMetric(sharedMetric)
                                            ? LEGACY_SHARED_METRIC_DUPLICATE_REASON
                                            : undefined
                                    }
                                    onClick={() => {
                                        router.actions.push(urls.experimentsSharedMetric(sharedMetric.id, 'duplicate'))
                                    }}
                                >
                                    Duplicate
                                </LemonButton>
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    icon={<IconTrash />}
                                    status="danger"
                                    loading={deleteCheckMetricId === sharedMetric.id}
                                    onClick={() => void handleDelete(sharedMetric.id)}
                                >
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="deprecated-space-y-4">
            <LemonBanner type="info">{SHARED_METRICS_INTRO}</LemonBanner>
            <div className="flex justify-between items-center gap-2">
                <div className="flex items-center gap-2">
                    <LemonInput
                        type="search"
                        placeholder="Search shared metrics..."
                        value={searchTerm}
                        onChange={setSearchTerm}
                    />
                    {count ? (
                        <span className="text-secondary whitespace-nowrap">
                            {`${startCount}${endCount > startCount ? '-' + endCount : ''} of ${pluralize(
                                count,
                                'metric'
                            )}`}
                        </span>
                    ) : null}
                </div>
                <LemonButton size="small" type="primary" to={urls.experimentsSharedMetric('new')}>
                    New shared metric
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={sharedMetrics}
                loading={sharedMetricsLoading}
                emptyState={<div>{SHARED_METRICS_EMPTY}</div>}
            />
            {count > PAGE_SIZE ? (
                <div className="flex items-center justify-end gap-1">
                    <span className="text-secondary whitespace-nowrap">
                        {`${startCount}${endCount > startCount ? '-' + endCount : ''} of ${pluralize(count, 'metric')}`}
                    </span>
                    <LemonButton
                        icon={<IconChevronLeft />}
                        size="small"
                        disabledReason={page <= 1 ? 'No previous page' : undefined}
                        onClick={() => setPage(page - 1)}
                    />
                    <LemonButton
                        icon={<IconChevronRight />}
                        size="small"
                        disabledReason={endCount >= count ? 'No next page' : undefined}
                        onClick={() => setPage(page + 1)}
                    />
                </div>
            ) : null}
        </div>
    )
}

export default ExperimentsSharedMetricsScene
