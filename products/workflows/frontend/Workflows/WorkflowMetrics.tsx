import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonCollapse, LemonSelect, ProfilePicture, Spinner } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { ListHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'
import { EmailMetricsSummary } from './EmailMetricsSummary'
import { getHogFlowStep } from './hogflows/steps/HogFlowSteps'
import { HogFlowBatchJob } from './hogflows/types'
import { WorkflowLogicProps, workflowLogic } from './workflowLogic'
import { WorkflowMetricsSummary } from './WorkflowMetricsSummary'

const OVERVIEW_OPTION_VALUE = '__workflow_overview__'

export const WORKFLOW_METRICS_INFO: Record<string, { name: string; description: string; color: string }> = {
    succeeded: {
        name: 'Success',
        description: 'Total number of events processed successfully',
        color: getColorVar('success'),
    },
    failed: {
        name: 'Failure',
        description: 'Total number of events that had errors during processing',
        color: getColorVar('danger'),
    },
    rate_limited: {
        name: 'Rate Limited',
        description: 'Total number of events that were rate limited',
        color: getColorVar('danger'),
    },
    triggered: {
        name: 'Triggered',
        description: 'Total number of events that were triggered',
        color: getColorVar('success'),
    },
}

function WorkflowRunMetrics(props: WorkflowLogicProps): JSX.Element {
    const logicKey = `hog-flow-metrics-${props.id}`

    const logic = appMetricsLogic({
        logicKey,
        loadOnChanges: true,
        loadOnMount: true,
        forceParams: {
            appSource: 'hog_flow',
            appSourceId: props.id,
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
                          color: WORKFLOW_METRICS_INFO[series.name as keyof typeof WORKFLOW_METRICS_INFO]?.color,
                      })),
                  }
                : null,
        [appMetricsTrends]
    )

    const workflowStepOptions = useMemo(
        () => [
            {
                label: 'Overview',
                value: OVERVIEW_OPTION_VALUE,
            },
            ...workflow.actions.map((action) => {
                const Step = getHogFlowStep(action, hogFunctionTemplatesById)
                return {
                    label: action.name,
                    icon: Step?.icon,
                    value: action.id,
                }
            }),
        ],
        [workflow.actions, hogFunctionTemplatesById]
    )

    return (
        <div className="flex flex-col gap-2" data-attr="workflow-metrics">
            <div className="flex flex-row gap-2 flex-wrap justify-between">
                <div>
                    <LemonSelect
                        size="small"
                        options={workflowStepOptions.filter((option) => option.value !== 'trigger_node')}
                        value={params.instanceId ?? OVERVIEW_OPTION_VALUE}
                        onChange={(value) =>
                            setParams({
                                ...params,
                                instanceId: value === OVERVIEW_OPTION_VALUE ? undefined : value,
                            })
                        }
                    />
                </div>
                <AppMetricsFilters logicKey={logicKey} />
            </div>

            {!params.instanceId || params.instanceId === OVERVIEW_OPTION_VALUE ? (
                <WorkflowMetricsSummary
                    logicKey={logicKey}
                    id={props.id ?? ''}
                    onSelectAction={(actionId) => setParams({ ...params, instanceId: actionId })}
                />
            ) : selectedAction?.type === 'function_email' ? (
                <EmailMetricsSummary logicKey={logicKey} />
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
                    <AppMetricsTrends appMetricsTrends={modifiedAppMetricsTrends} loading={appMetricsTrendsLoading} />
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
                          color: WORKFLOW_METRICS_INFO[series.name as keyof typeof WORKFLOW_METRICS_INFO]?.color,
                      })),
                  }
                : null,
        [appMetricsTrends]
    )

    const workflowStepOptions = useMemo(
        () => [
            {
                label: 'Overview',
                value: OVERVIEW_OPTION_VALUE,
            },
            ...workflow.actions.map((action) => {
                const Step = getHogFlowStep(action, hogFunctionTemplatesById)
                return {
                    label: action.name,
                    icon: Step?.icon,
                    value: action.id,
                }
            }),
        ],
        [workflow.actions, hogFunctionTemplatesById]
    )

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-row gap-2 flex-wrap justify-between">
                <div>
                    <LemonSelect
                        size="small"
                        options={workflowStepOptions.filter((option) => option.value !== 'trigger_node')}
                        value={params.instanceId ?? OVERVIEW_OPTION_VALUE}
                        onChange={(value) =>
                            setParams({
                                ...params,
                                instanceId: value === OVERVIEW_OPTION_VALUE ? undefined : value,
                            })
                        }
                    />
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
                    <AppMetricsTrends appMetricsTrends={modifiedAppMetricsTrends} loading={appMetricsTrendsLoading} />
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
                <ListHog width="100" height="100" className="mb-4" />
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
