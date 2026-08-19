import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTable, LemonTableColumns, lemonToast, Link } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AnnotatedLineChart } from './components/AnnotatedLineChart'
import { DEMO_REPORT_ID } from './mockData'

const CARD_CLASSES = 'p-5 rounded-lg flex flex-col gap-3'
const MICRO_LABEL_CLASSES = 'm-0 text-[10px] font-semibold tracking-wide uppercase text-secondary'

interface ComparisonRow {
    metric: string
    treated: string
    control: string
    confidence: string
}

const COMPARISON_ROWS: ComparisonRow[] = [
    { metric: 'TOKEN_EXPIRED errors/hr', treated: '1.8', control: '41.2', confidence: '>99.9%' },
    { metric: 'Returning-user conversion', treated: '83.9%', control: '72.4%', confidence: '99.2%' },
    { metric: 'Silent Pay-tap sessions/day', treated: '0', control: '196', confidence: '>99.9%' },
]

const COMPARISON_COLUMNS: LemonTableColumns<ComparisonRow> = [
    { title: 'Metric', dataIndex: 'metric' },
    {
        title: 'Fallback on',
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
    {
        title: 'Confidence',
        dataIndex: 'confidence',
        align: 'right',
        render: (confidence) => <span className="font-mono text-secondary">{confidence}</span>,
    },
]

interface SuccessCriterion {
    label: string
    detail: string
    value: string
    met: boolean
}

const SUCCESS_CRITERIA: SuccessCriterion[] = [
    { label: 'Error rate back to baseline', detail: 'target ≤ 2/hr · met day 1', value: '1.8/hr', met: true },
    { label: 'No new matching tickets', detail: 'target 0 · 4 days clean', value: '0', met: true },
    { label: 'Conversion recovers', detail: 'target ≥ 84% · blended, trending up', value: '83.6%', met: false },
]

interface SurveyAnswer {
    label: string
    percent: number
    barColor: string
    valueClassName: string
}

const SURVEY_ANSWERS: SurveyAnswer[] = [
    { label: 'Yes', percent: 92, barColor: 'var(--success)', valueClassName: 'text-success' },
    { label: 'No', percent: 5, barColor: 'var(--danger)', valueClassName: 'text-secondary' },
    { label: 'Unsure', percent: 3, barColor: 'var(--color-text-tertiary)', valueClassName: 'text-secondary' },
]

/**
 * Post-launch fix monitor for the investigations inbox redesign preview. Static
 * mock content, so there is no logic file. The 1160px column matches the other
 * demo pages so they line up when clicked through in sequence.
 */
export function InvestigationsMonitorScene(): JSX.Element {
    return (
        <div className="max-w-[1160px] mx-auto flex flex-col gap-4">
            <div className="flex">
                <Link
                    to={urls.investigationsDemoReport(DEMO_REPORT_ID)}
                    subtle
                    className="text-xs text-secondary"
                    data-attr="investigations-demo-monitor-back-to-report"
                >
                    ← {DEMO_REPORT_ID} report
                </Link>
            </div>

            <LemonCard
                hoverEffect={false}
                className="p-5 rounded-lg flex items-center gap-6 max-lg:flex-col max-lg:items-stretch"
            >
                <div className="flex flex-col gap-0.5 min-w-56">
                    <span className="text-xs text-secondary">
                        Flag rollout · <span className="font-mono">checkout_token_refresh_fallback</span>
                    </span>
                    <span className="font-mono text-xl font-semibold">50%</span>
                </div>
                <div className="flex-1 flex flex-col gap-2">
                    <LemonProgress percent={50} strokeColor="var(--color-accent)" />
                    <div className="flex justify-between gap-2 font-mono text-xs">
                        <span className="text-success">10% · Aug 18 ✓</span>
                        <span className="font-semibold text-accent">50% · Aug 19 ← now</span>
                        <span className="text-tertiary">100% · scheduled Aug 21</span>
                    </div>
                </div>
                <div className="flex flex-col gap-1.5 items-end max-lg:items-stretch">
                    <LemonButton
                        type="primary"
                        onClick={() => lemonToast.info('Not part of this demo')}
                        data-attr="investigations-demo-monitor-ramp-to-full"
                    >
                        Ramp to 100% now
                    </LemonButton>
                    <span className="text-xs text-tertiary">auto-halt armed · 0 breaches</span>
                </div>
            </LemonCard>

            <div className="grid grid-cols-[1.4fr_1fr] gap-4 items-start max-lg:grid-cols-1">
                <div className="flex flex-col gap-4">
                    <LemonCard hoverEffect={false} className={CARD_CLASSES}>
                        <div className="flex items-center justify-between gap-2">
                            <h3 className="m-0 text-sm font-semibold">Recovery</h3>
                            <span className="font-mono text-[10px] text-tertiary">
                                TOKEN_EXPIRED errors/hr · Aug 14–22
                            </span>
                        </div>
                        <AnnotatedLineChart
                            viewWidth={560}
                            viewHeight={150}
                            series={[
                                {
                                    points: '0,130 20,124 40,60 70,40 110,30 160,24 210,22 260,20 300,21 330,52 356,58 380,96 410,112 440,120 480,126 520,128 560,129',
                                    color: 'accent',
                                },
                            ]}
                            baselineY={132}
                            baselineLabel="baseline 2/hr"
                            annotations={[
                                { x: 40, label: 'a3f9c21', color: 'danger' },
                                { x: 330, label: 'fix 10%', color: 'success' },
                                { x: 380, label: '50%', color: 'success' },
                            ]}
                        />
                        <p className="m-0 text-xs text-secondary">
                            Error rate in the treated cohort is at 1.8/hr, back to baseline within 40 minutes of each
                            ramp step. Untreated traffic still fails at ~41/hr, which is the remaining gap.
                        </p>
                    </LemonCard>

                    <LemonCard hoverEffect={false} className={CARD_CLASSES}>
                        <div className="flex items-center justify-between gap-2">
                            <h3 className="m-0 text-sm font-semibold">Treated vs control</h3>
                            <span className="text-[10px] text-tertiary">returning users · since Aug 18</span>
                        </div>
                        <LemonTable
                            columns={COMPARISON_COLUMNS}
                            dataSource={COMPARISON_ROWS}
                            rowKey="metric"
                            size="small"
                            embedded
                        />
                        <p className="m-0 text-xs text-secondary">
                            Guardrails clean: latency p95 +4ms (n.s.), payment success +0.2pt, crash rate unchanged.
                        </p>
                    </LemonCard>
                </div>

                <div className="flex flex-col gap-4">
                    <LemonCard hoverEffect={false} className={CARD_CLASSES}>
                        <h3 className={MICRO_LABEL_CLASSES}>Success criteria · 2 of 3 met</h3>
                        <div className="flex flex-col">
                            {SUCCESS_CRITERIA.map((criterion) => (
                                <div
                                    key={criterion.label}
                                    className="flex items-center gap-2.5 py-2 border-b border-primary last:border-b-0"
                                >
                                    <span
                                        className={cn(
                                            'flex-none flex items-center justify-center size-4 rounded-full',
                                            criterion.met
                                                ? 'bg-success-highlight text-success'
                                                : 'bg-fill-tertiary text-tertiary'
                                        )}
                                    >
                                        {criterion.met ? (
                                            <IconCheck className="text-[10px]" />
                                        ) : (
                                            <span className="text-[10px] font-semibold">…</span>
                                        )}
                                    </span>
                                    <div className="flex-1 flex flex-col">
                                        <span className="text-xs text-primary">{criterion.label}</span>
                                        <span className="font-mono text-[10px] text-tertiary">{criterion.detail}</span>
                                    </div>
                                    <span
                                        className={cn(
                                            'font-mono text-xs font-semibold',
                                            criterion.met ? 'text-success' : 'text-secondary'
                                        )}
                                    >
                                        {criterion.value}
                                    </span>
                                </div>
                            ))}
                        </div>
                        <p className="m-0 text-xs text-secondary">
                            Conversion needs the 100% ramp to clear 84%. The control half is still dragging the blended
                            number.
                        </p>
                    </LemonCard>

                    <LemonCard hoverEffect={false} className={CARD_CLASSES}>
                        <div className="flex items-center justify-between gap-2">
                            <h3 className={MICRO_LABEL_CLASSES}>Survey</h3>
                            <span className="font-mono text-[10px] text-secondary">412 sent · 187 responses</span>
                        </div>
                        <p className="m-0 text-xs text-primary">“Did payment work this time?”</p>
                        <div className="flex flex-col gap-1.5">
                            {SURVEY_ANSWERS.map((answer) => (
                                <div key={answer.label} className="flex items-center gap-2">
                                    <span className="w-11 flex-none text-xs text-secondary">{answer.label}</span>
                                    <LemonProgress
                                        percent={answer.percent}
                                        strokeColor={answer.barColor}
                                        bgColor="var(--color-bg-fill-tertiary)"
                                        className="flex-1"
                                    />
                                    <span className={cn('w-8 text-right font-mono text-[10px]', answer.valueClassName)}>
                                        {answer.percent}%
                                    </span>
                                </div>
                            ))}
                        </div>
                        <p className="m-0 text-xs italic text-secondary">“Went through first try. Glad it’s fixed.”</p>
                        <p className="m-0 text-[10px] text-tertiary">
                            The 9 “No” responses are all in the control cohort.
                        </p>
                    </LemonCard>

                    <LemonCard hoverEffect={false} className="p-5 rounded-lg flex flex-col gap-2.5">
                        <h3 className={MICRO_LABEL_CLASSES}>What happens next</h3>
                        <p className="m-0 text-xs text-secondary">
                            On current pace, all criteria hold by <strong className="text-primary">Aug 25</strong>.{' '}
                            {DEMO_REPORT_ID} is then reopened, updated with these results, and marked resolved.
                            Subscribers get the diff instead of a new report.
                        </p>
                        <Link
                            to={urls.investigationsDemoResolved(DEMO_REPORT_ID)}
                            className="text-xs font-semibold"
                            data-attr="investigations-demo-monitor-preview-updated-report"
                        >
                            Preview the updated report →
                        </Link>
                    </LemonCard>
                </div>
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: InvestigationsMonitorScene,
}

export default InvestigationsMonitorScene
