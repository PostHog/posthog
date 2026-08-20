import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AnnotatedLineChart } from './components/AnnotatedLineChart'
import { InboxBackButton } from './components/InboxBackButton'
import { getDemoReport } from './mockData'
import { MONITOR_FLAG_KEY, MonitorComparisonRow, MonitorRolloutStepState, v2MonitorLogic } from './v2MonitorLogic'

/** The scenario this page is written around; other ids reuse the same demo monitor. */
const MONITOR_DEMO_REPORT_ID = 'RPT-1028'
const FALLBACK_HEADLINE = 'Stackless Firefox errors were collapsing into one giant issue'
const FALLBACK_AREA = 'ERROR TRACKING'

/** The resolved page this monitor previews, once the 7-day window closes. */
const RESOLVED_EXAMPLE_ID = 'RPT-1019'

const CARD_CLASSES = 'p-5 rounded-lg flex flex-col gap-3'
const MICRO_LABEL_CLASSES = 'm-0 text-[10px] font-semibold tracking-wide uppercase text-secondary'

const STEP_CLASSES: Record<MonitorRolloutStepState, string> = {
    done: 'text-success',
    now: 'font-semibold text-accent',
    scheduled: 'text-tertiary',
}

const STEP_STAMP: Record<MonitorRolloutStepState, string> = {
    done: ' ✓',
    now: ' ← now',
    scheduled: '',
}

const COMPARISON_COLUMNS: LemonTableColumns<MonitorComparisonRow> = [
    { title: 'Metric', dataIndex: 'metric' },
    {
        title: 'Treated',
        dataIndex: 'treated',
        align: 'right',
        render: (treated) => <span className="font-mono font-semibold text-success">{treated}</span>,
    },
    {
        title: 'Control',
        dataIndex: 'control',
        align: 'right',
        render: (control) => <span className="font-mono text-secondary">{control}</span>,
    },
]

export interface V2MonitorSceneProps {
    id?: string
}

/**
 * Post-fix monitor for the reports inbox redesign preview: a live recovery
 * window, a drifting comparison, and a flag ramp that can be run. The 1160px
 * column matches the other demo pages so they line up when clicked through.
 */
export function V2MonitorScene({ id = MONITOR_DEMO_REPORT_ID }: V2MonitorSceneProps): JSX.Element {
    const logic = v2MonitorLogic({ id })
    const {
        comparisonRows,
        freshnessLabel,
        rampComplete,
        ramping,
        recoveryChart,
        rolloutPercent,
        rolloutSteps,
        signalChecks,
    } = useValues(logic)
    const { startRamp } = useActions(logic)

    const report = getDemoReport(id)
    const headline = report?.headline ?? FALLBACK_HEADLINE
    const area = report?.area ?? FALLBACK_AREA
    const metCount = signalChecks.filter((check) => check.met).length

    return (
        <div className="flex flex-col gap-4">
            <InboxBackButton className="self-start -ml-[var(--button-padding-x-base)]" />
            <div className="max-w-[1160px] mx-auto flex w-full flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                    <div className="flex flex-wrap items-center gap-3">
                        <span className="text-[15px] font-bold">{id}</span>
                        <span className="font-mono text-[10px] font-semibold tracking-wide uppercase text-tertiary">
                            {area}
                        </span>
                    </div>
                    <div className="flex flex-wrap items-baseline gap-3">
                        <h1 className="m-0 text-xl font-bold">{headline}</h1>
                        <span className="font-mono text-xs text-tertiary">{freshnessLabel}</span>
                    </div>
                </div>

                <LemonCard
                    hoverEffect={false}
                    className="p-5 rounded-lg flex items-center gap-6 max-lg:flex-col max-lg:items-stretch"
                >
                    <div className="flex flex-col gap-0.5 min-w-56">
                        <span className="text-xs text-secondary">
                            Flag rollout · <span className="font-mono">{MONITOR_FLAG_KEY}</span>
                        </span>
                        <span className="font-mono text-xl font-semibold">{rolloutPercent}%</span>
                    </div>
                    <div className="flex-1 flex flex-col gap-2">
                        <LemonProgress percent={rolloutPercent} strokeColor="var(--color-accent)" />
                        <div className="flex justify-between gap-2 font-mono text-xs">
                            {rolloutSteps.map((step) => (
                                <span key={step.label} className={STEP_CLASSES[step.state]}>
                                    {step.label}
                                    {STEP_STAMP[step.state]}
                                </span>
                            ))}
                        </div>
                    </div>
                    <div className="flex flex-col gap-1.5 items-end max-lg:items-stretch">
                        <LemonButton
                            type="primary"
                            onClick={startRamp}
                            loading={ramping}
                            disabledReason={rampComplete ? 'The flag is already at 100%' : undefined}
                            data-attr="v2-monitor-ramp"
                        >
                            {rampComplete ? 'Rolled out to 100%' : 'Ramp to 100% now'}
                        </LemonButton>
                        <span className="text-xs text-tertiary max-lg:text-left">
                            stackless rate above 2x the ramp baseline reverts the flag in 60s
                        </span>
                    </div>
                </LemonCard>

                <div className="grid grid-cols-[1.4fr_1fr] gap-4 items-start max-lg:grid-cols-1">
                    <div className="flex flex-col gap-4">
                        <LemonCard hoverEffect={false} className={CARD_CLASSES}>
                            <div className="flex items-center justify-between gap-2">
                                <h3 className="m-0 text-sm font-semibold">Recovery</h3>
                                <span className="font-mono text-[10px] text-tertiary">
                                    stackless captures per hour · trailing 24h
                                </span>
                            </div>
                            <AnnotatedLineChart data={recoveryChart} viewWidth={640} height={220} live />
                            <p className="m-0 text-xs text-secondary">
                                Captures without a stack ran around 60 per hour before the fix. They have stayed under
                                the 5 per hour target since, and the window keeps sliding while this page is open.
                            </p>
                        </LemonCard>

                        <LemonCard hoverEffect={false} className={CARD_CLASSES}>
                            <div className="flex items-center justify-between gap-2">
                                <h3 className="m-0 text-sm font-semibold">Treated vs control</h3>
                                <span className="font-mono text-[10px] text-tertiary">{MONITOR_FLAG_KEY} · 50/50</span>
                            </div>
                            <LemonTable
                                columns={COMPARISON_COLUMNS}
                                dataSource={comparisonRows}
                                rowKey="metric"
                                size="small"
                                embedded
                            />
                            <p className="m-0 text-xs text-secondary">
                                Treated traffic splits stackless captures into issues you can act on. Control still
                                funnels everything into the one catch-all issue, so it shows a single issue holding
                                thousands of events.
                            </p>
                        </LemonCard>
                    </div>

                    <div className="flex flex-col gap-4">
                        <LemonCard hoverEffect={false} className={CARD_CLASSES}>
                            <h3 className={MICRO_LABEL_CLASSES}>
                                Signal checks · {metCount} of {signalChecks.length} met
                            </h3>
                            <div className="flex flex-col">
                                {signalChecks.map((check) => (
                                    <div
                                        key={check.label}
                                        className="flex items-center gap-2.5 py-2 border-b border-primary last:border-b-0"
                                    >
                                        <span
                                            className={cn(
                                                'flex-none flex items-center justify-center size-4 rounded-full',
                                                check.met
                                                    ? 'bg-success-highlight text-success'
                                                    : 'bg-fill-tertiary text-tertiary'
                                            )}
                                        >
                                            {check.met ? (
                                                <IconCheck className="text-[10px]" />
                                            ) : (
                                                <span className="text-[10px] font-semibold">…</span>
                                            )}
                                        </span>
                                        <div className="flex-1 flex flex-col">
                                            <span className="text-xs text-primary">{check.label}</span>
                                            <span className="font-mono text-[10px] text-tertiary">{check.detail}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                            <p className="m-0 text-xs text-secondary">
                                The first three checks passed within an hour of the fix. The 7-day hold is the only one
                                still running.
                            </p>
                        </LemonCard>

                        <LemonCard hoverEffect={false} className="p-5 rounded-lg flex flex-col gap-2.5">
                            <h3 className={MICRO_LABEL_CLASSES}>What happens next</h3>
                            <p className="m-0 text-xs text-secondary">
                                If the checks hold for 7 days, {id} resolves itself and an epilogue with the closing
                                numbers is appended. Nobody has to come back and mark it done.
                            </p>
                            <Link
                                to={urls.v2Resolved(RESOLVED_EXAMPLE_ID)}
                                className="text-xs font-semibold"
                                data-attr="v2-monitor-see-resolved"
                            >
                                See what a resolved report looks like →
                            </Link>
                            <Link
                                to={urls.v2Report(id)}
                                subtle
                                className="text-xs text-secondary"
                                data-attr="v2-monitor-open-full-report"
                            >
                                Back to the full report
                            </Link>
                        </LemonCard>
                    </div>
                </div>
            </div>
        </div>
    )
}

export const scene: SceneExport<V2MonitorSceneProps> = {
    component: V2MonitorScene,
    logic: v2MonitorLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id ?? MONITOR_DEMO_REPORT_ID }),
}

export default V2MonitorScene
