import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import * as greekPng from '@posthog/brand/hoggies/png/greek'
import { IconLetter } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonSelect, LemonSelectOptions, ProfilePicture, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { getColorVar } from 'lib/colors'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'
import { EmailMetricsSummary } from './EmailMetricsSummary'
import { getHogFlowStep } from './hogflows/steps/HogFlowSteps'
import { HogFlowBatchJob } from './hogflows/types'
import { PushMetricsSummary } from './PushMetricsSummary'
import { WorkflowLogicProps, workflowLogic } from './workflowLogic'
import { WorkflowMetricsSummary } from './WorkflowMetricsSummary'
import { type EmailMetric, METRIC_COLORS, buildEmailMetricInvocationSearchParams } from './workflowMetricsSummaryLogic'

const HedgehogGreek = pngHoggie(greekPng)

const OVERVIEW_OPTION_VALUE = '__workflow_overview__'

export const WORKFLOW_METRICS_INFO: Record<string, { name: string; description: string; color: string }> = {
    succeeded: {
        name: 'Success',
        description: 'Total number of events processed successfully',
        color: METRIC_COLORS['Success'],
    },
    failed: {
        name: 'Failure',
        description: 'Total number of events that had errors during processing',
        color: METRIC_COLORS['Failure'],
    },
    rate_limited: {
        name: 'Rate Limited',
        description: 'Total number of events that were rate limited',
        color: METRIC_COLORS['Rate Limited'],
    },
    triggered: {
        name: 'Triggered',
        description: 'Total number of events that were triggered',
        color: METRIC_COLORS['Triggered'],
    },
}

function WorkflowRunMetrics(props: WorkflowLogicProps): JSX.Element {
    const logicKey = `hog-flow-metrics-${props.id}`
    const { searchParams } = useValues(router)
    const { workflow, hogFunctionTemplatesById } = useValues(workflowLogic)

    // Seed the drilled-in step from ?action= so a refreshed or shared metrics link restores it, but
    // only honor a value that points at a real step — a stale/deleted/mistyped id would otherwise
    // select a nonexistent instance and get stuck in the generic step view. While the workflow is
    // still loading (no actions yet) we honor it optimistically so a shared link doesn't flash the
    // overview first. Later changes (clicks, back/forward) are synced by workflowSceneLogic's urlToAction.
    const requestedAction = (searchParams.action as string) || undefined
    const instanceId =
        requestedAction &&
        (!workflow.actions.length || workflow.actions.some((action) => action.id === requestedAction))
            ? requestedAction
            : undefined

    const logic = appMetricsLogic({
        logicKey,
        loadOnChanges: true,
        loadOnMount: true,
        forceParams: {
            appSource: 'hog_flow',
            appSourceId: props.id,
            breakdownBy: 'metric_name',
            instanceId,
        },
    })

    const { appMetricsTrendsLoading, appMetricsTrends, getSingleTrendSeries, params, getDateRangeAbsolute } =
        useValues(logic)

    const selectedAction = workflow.actions.find((action) => action.id === params.instanceId)

    const modifiedAppMetricsTrends = useMemo(
        () =>
            appMetricsTrends
                ? {
                      ...appMetricsTrends,
                      series: appMetricsTrends.series.map((series) => ({
                          ...series,
                          name:
                              WORKFLOW_METRICS_INFO[series.name as keyof typeof WORKFLOW_METRICS_INFO]?.name ??
                              series.name,
                      })),
                  }
                : null,
        [appMetricsTrends]
    )

    const workflowStepOptions: LemonSelectOptions<string> = useMemo(
        () => [
            {
                options: [{ label: 'Whole workflow', value: OVERVIEW_OPTION_VALUE }],
            },
            {
                // A titled section makes it obvious you can drill into a single step's metrics.
                title: 'Per step',
                options: workflow.actions
                    .filter((action) => action.id !== 'trigger_node')
                    .map((action) => {
                        const Step = getHogFlowStep(action, hogFunctionTemplatesById)
                        return {
                            label: action.name,
                            icon: Step?.icon,
                            value: action.id,
                        }
                    }),
            },
        ],
        [workflow.actions, hogFunctionTemplatesById]
    )

    // Drill an email metric into the invocations behind it over the current window.
    const onEmailMetricClick = (metricKey: EmailMetric): void => {
        if (!props.id) {
            return
        }
        const { dateFrom, dateTo } = getDateRangeAbsolute()
        const invocationSearchParams = buildEmailMetricInvocationSearchParams(
            metricKey,
            dateFrom.toISOString(),
            dateTo.toISOString()
        )
        if (invocationSearchParams) {
            router.actions.push(urls.workflow(props.id, 'invocations'), invocationSearchParams)
        }
    }

    // Reflect the selected step in the URL (?action=) so it survives refresh/share/back-forward. The
    // actual params.instanceId update is applied by workflowSceneLogic's urlToAction watching this.
    const selectMetricsAction = (actionId?: string): void => {
        if (!props.id) {
            return
        }
        const { action: _prev, ...rest } = searchParams
        router.actions.push(urls.workflow(props.id, 'metrics'), actionId ? { ...rest, action: actionId } : rest)
    }

    return (
        <div className="flex flex-col gap-2" data-attr="workflow-metrics">
            <div className="flex flex-row gap-2 flex-wrap justify-end items-center">
                <div className="flex flex-row gap-2 items-center flex-wrap">
                    <span className="text-muted text-xs whitespace-nowrap">Metrics for</span>
                    <LemonSelect
                        size="small"
                        options={workflowStepOptions}
                        value={params.instanceId ?? OVERVIEW_OPTION_VALUE}
                        onChange={(value) => selectMetricsAction(value === OVERVIEW_OPTION_VALUE ? undefined : value)}
                    />
                    {selectedAction?.type === 'function_email' && props.id ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconLetter />}
                            to={`${urls.workflow(props.id, 'assets')}?assetAction=${encodeURIComponent(params.instanceId as string)}`}
                        >
                            View sent emails
                        </LemonButton>
                    ) : null}
                </div>
                <AppMetricsFilters logicKey={logicKey} />
            </div>

            {!params.instanceId || params.instanceId === OVERVIEW_OPTION_VALUE ? (
                <WorkflowMetricsSummary
                    logicKey={logicKey}
                    id={props.id ?? ''}
                    onSelectAction={(actionId) => selectMetricsAction(actionId)}
                    onMetricClick={onEmailMetricClick}
                />
            ) : selectedAction?.type === 'function_email' ? (
                <EmailMetricsSummary logicKey={logicKey} onMetricClick={onEmailMetricClick} />
            ) : selectedAction?.type === 'function_push' ? (
                <PushMetricsSummary logicKey={logicKey} />
            ) : (
                <>
                    <div className="flex flex-row gap-2 flex-wrap justify-center">
                        {['succeeded', 'failed'].map((key) => (
                            <AppMetricSummary
                                key={key}
                                name={WORKFLOW_METRICS_INFO[key].name}
                                description={WORKFLOW_METRICS_INFO[key].description}
                                loading={appMetricsTrendsLoading}
                                timeSeries={getSingleTrendSeries(key)}
                                previousPeriodTimeSeries={getSingleTrendSeries(key, true)}
                                color={WORKFLOW_METRICS_INFO[key].color}
                                colorIfZero={getColorVar('muted')}
                            />
                        ))}
                    </div>
                    <AppMetricsTrends
                        appMetricsTrends={modifiedAppMetricsTrends}
                        loading={appMetricsTrendsLoading}
                        seriesColors={METRIC_COLORS}
                    />
                </>
            )}
        </div>
    )
}

function BatchJobMetricsHeader({ job }: { job: HogFlowBatchJob }): JSX.Element {
    return (
        <div className="flex gap-2 w-full justify-between">
            <strong>{job.id}</strong>
            <div className="flex items-center gap-2">
                <TZLabel title="Created at" time={job.created_at} />
                {job.created_by ? (
                    <ProfilePicture user={{ email: job.created_by.email || '' }} showName size="sm" />
                ) : (
                    <span className="text-muted text-sm">Scheduled run</span>
                )}
            </div>
        </div>
    )
}

function BatchJobMetrics({ job }: { job: HogFlowBatchJob }): JSX.Element {
    const logicKey = `hog-flow-metrics-batch-${job.id}`

    const jobStart = dayjs(job.created_at).subtract(1, 'hour')
    const isFinished = job.status === 'completed' || job.status === 'cancelled' || job.status === 'failed'
    const jobEnd = isFinished ? dayjs(job.updated_at).add(1, 'hour') : dayjs()

    const logic = appMetricsLogic({
        logicKey,
        loadOnChanges: true,
        loadOnMount: true,
        defaultParams: {
            dateFrom: jobStart.toISOString(),
            dateTo: jobEnd.toISOString(),
        },
        forceParams: {
            appSource: 'hog_flow',
            appSourceId: job.id,
            breakdownBy: 'metric_name',
        },
    })

    const { workflow, hogFunctionTemplatesById } = useValues(workflowLogic)

    const { appMetricsTrendsLoading, appMetricsTrends, getSingleTrendSeries, params } = useValues(logic)
    const { setParams } = useActions(logic)

    const selectedAction = workflow.actions.find((action) => action.id === params.instanceId)

    const modifiedAppMetricsTrends = useMemo(
        () =>
            appMetricsTrends
                ? {
                      ...appMetricsTrends,
                      series: appMetricsTrends.series.map((series) => ({
                          ...series,
                          name:
                              WORKFLOW_METRICS_INFO[series.name as keyof typeof WORKFLOW_METRICS_INFO]?.name ??
                              series.name,
                      })),
                  }
                : null,
        [appMetricsTrends]
    )

    const workflowStepOptions: LemonSelectOptions<string> = useMemo(
        () => [
            {
                options: [{ label: 'Whole workflow', value: OVERVIEW_OPTION_VALUE }],
            },
            {
                // A titled section makes it obvious you can drill into a single step's metrics.
                title: 'Per step',
                options: workflow.actions
                    .filter((action) => action.id !== 'trigger_node')
                    .map((action) => {
                        const Step = getHogFlowStep(action, hogFunctionTemplatesById)
                        return {
                            label: action.name,
                            icon: Step?.icon,
                            value: action.id,
                        }
                    }),
            },
        ],
        [workflow.actions, hogFunctionTemplatesById]
    )

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-row gap-2 flex-wrap justify-end items-center">
                <div className="flex flex-row gap-2 items-center flex-wrap">
                    <span className="text-muted text-xs whitespace-nowrap">Metrics for</span>
                    <LemonSelect
                        size="small"
                        options={workflowStepOptions}
                        value={params.instanceId ?? OVERVIEW_OPTION_VALUE}
                        onChange={(value) =>
                            setParams({
                                ...params,
                                instanceId: value === OVERVIEW_OPTION_VALUE ? undefined : value,
                            })
                        }
                    />
                    {selectedAction?.type === 'function_email' ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconLetter />}
                            to={`${urls.workflow(workflow.id, 'assets')}?assetAction=${encodeURIComponent(params.instanceId as string)}`}
                        >
                            View sent emails
                        </LemonButton>
                    ) : null}
                </div>
                <AppMetricsFilters logicKey={logicKey} />
            </div>

            {!params.instanceId || params.instanceId === OVERVIEW_OPTION_VALUE ? (
                <WorkflowMetricsSummary
                    logicKey={logicKey}
                    id={workflow.id}
                    appSourceId={job.id}
                    onSelectAction={(actionId) => setParams({ ...params, instanceId: actionId })}
                />
            ) : selectedAction?.type === 'function_email' ? (
                <EmailMetricsSummary logicKey={logicKey} />
            ) : selectedAction?.type === 'function_push' ? (
                <PushMetricsSummary logicKey={logicKey} />
            ) : (
                <>
                    <div className="flex flex-row gap-2 flex-wrap justify-center">
                        {['succeeded', 'failed'].map((key) => (
                            <AppMetricSummary
                                key={key}
                                name={WORKFLOW_METRICS_INFO[key].name}
                                description={WORKFLOW_METRICS_INFO[key].description}
                                loading={appMetricsTrendsLoading}
                                timeSeries={getSingleTrendSeries(key)}
                                previousPeriodTimeSeries={getSingleTrendSeries(key, true)}
                                color={WORKFLOW_METRICS_INFO[key].color}
                                colorIfZero={getColorVar('muted')}
                            />
                        ))}
                    </div>
                    <AppMetricsTrends
                        appMetricsTrends={modifiedAppMetricsTrends}
                        loading={appMetricsTrendsLoading}
                        seriesColors={METRIC_COLORS}
                    />
                </>
            )}
        </div>
    )
}

function WorkflowBatchMetrics(props: WorkflowLogicProps): JSX.Element {
    const { jobs, batchWorkflowJobsLoading } = useValues(batchWorkflowJobsLogic(props))

    if (batchWorkflowJobsLoading) {
        return (
            <div className="flex justify-center">
                <Spinner size="medium" />
            </div>
        )
    }

    if (!jobs.length) {
        return (
            <div className="flex flex-col bg-surface-primary rounded px-4 py-8 items-center text-center mx-auto">
                <HedgehogGreek width="100" height="100" className="mb-4" />
                <h2 className="text-xl leading-tight">No batch workflow jobs have been run yet</h2>
                <p className="text-sm text-balance text-tertiary">
                    Once a batch workflow job is triggered, metrics will appear here.
                </p>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonCollapse
                panels={jobs.map((job) => ({
                    key: job.id,
                    header: <BatchJobMetricsHeader job={job} />,
                    content: <BatchJobMetrics job={job} />,
                }))}
            />
        </div>
    )
}

export function WorkflowMetrics(props: WorkflowLogicProps): JSX.Element {
    const { workflow, workflowLoading } = useValues(workflowLogic(props))

    if (workflowLoading) {
        return (
            <div className="flex justify-center">
                <Spinner size="medium" />
            </div>
        )
    }

    return workflow?.trigger?.type === 'batch' ? <WorkflowBatchMetrics {...props} /> : <WorkflowRunMetrics {...props} />
}
