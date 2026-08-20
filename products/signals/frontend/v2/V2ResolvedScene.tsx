import { LemonButton, LemonCollapse, LemonDivider, LemonTag, Link, lemonToast } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AnnotatedLineChart } from './components/AnnotatedLineChart'
import { InboxBackButton } from './components/InboxBackButton'
import { getDemoReport } from './mockData'
import { DemoChartData, ReportTimelineColor, ReportTimelineEntry } from './types'

/** The scenario this page is written around; other ids reuse the same demo epilogue. */
const RESOLVED_DEMO_REPORT_ID = 'RPT-1019'
const FALLBACK_AREA = 'FEATURE FLAGS'

/** Jul 28 through Aug 18, one point per day. */
const DAY_LABELS = [
    ...[28, 29, 30, 31].map((day) => `Jul ${day}`),
    ...Array.from({ length: 18 }, (_, index) => `Aug ${index + 1}`),
]

const WRONG_VARIANT_CHART: DemoChartData = {
    series: [
        {
            name: 'Wrong variant evaluations per day',
            color: 'accent',
            points: [8, 7, 96, 214, 258, 271, 266, 274, 269, 276, 272, 275, 270, 273, 118, 0, 0, 0, 0, 0, 0, 0],
        },
    ],
    pointLabels: DAY_LABELS,
    xLabels: ['Jul 28', 'Aug 7', 'Aug 18'],
    unit: 'per day',
    annotations: [
        { index: 2, label: 'cause ships', color: 'danger' },
        { index: 14, label: 'fix ships', color: 'success' },
    ],
}

const DOT_COLOR: Record<ReportTimelineColor, string> = {
    danger: 'bg-danger',
    muted: 'bg-[var(--color-text-tertiary)]',
    success: 'bg-success',
}

const CHIP_TEXT_COLOR: Record<ReportTimelineColor, string> = {
    danger: 'text-danger',
    muted: 'text-secondary',
    success: 'text-success',
}

const TIMELINE: ReportTimelineEntry[] = [
    {
        label: 'GeoIP enrichment reordered ahead of caller properties',
        time: 'Jul 30 09:02',
        chip: 'b2d47e1',
        color: 'danger',
    },
    { label: 'First wrong variant served', time: 'Jul 30 09:11', chip: '+9 min', color: 'muted' },
    { label: 'Detected, case opened', time: 'Aug 9 06:20', chip: 'auto', color: 'muted' },
    { label: 'Report published', time: 'Aug 9 06:47', chip: '27 min', color: 'muted' },
    { label: 'Fix shipped', time: 'Aug 11', chip: 'merged', color: 'success' },
    { label: 'Verified for 7 days, resolved', time: 'Aug 18', chip: 'auto', color: 'success' },
]

const DELTAS: { label: string; was: string; now: string; recovered: boolean }[] = [
    { label: 'Wrong variant evaluations per day', was: '276', now: '0', recovered: true },
    { label: 'Server SDK calls affected', was: '4.1%', now: '0%', recovered: true },
    { label: 'Flag-related support tickets per week', was: '5', now: '1', recovered: false },
]

function Microlabel({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="text-[11px] font-semibold tracking-wider text-secondary uppercase">{children}</div>
}

function Mono({ children }: { children: React.ReactNode }): JSX.Element {
    return <span className="font-mono text-[0.9em]">{children}</span>
}

export interface V2ResolvedSceneProps {
    id?: string
}

export function V2ResolvedScene({ id = RESOLVED_DEMO_REPORT_ID }: V2ResolvedSceneProps): JSX.Element {
    const report = getDemoReport(id)
    const area = report?.area ?? FALLBACK_AREA

    const copyPageLink = (): void => {
        navigator.clipboard?.writeText(window.location.href).catch(() => {})
        lemonToast.success('Link copied to clipboard')
    }

    return (
        <div className="flex flex-col gap-4">
            <InboxBackButton className="self-start -ml-[var(--button-padding-x-base)]" />
            <div className="mx-auto flex w-full max-w-[1360px] flex-col gap-4">
                <div className="flex flex-wrap items-center gap-3.5">
                    <span className="text-[15px] font-bold">{id}</span>
                    <span className="font-mono text-[11px] font-semibold tracking-wider text-secondary uppercase">
                        {area}
                    </span>
                    <LemonTag type="success">Resolved</LemonTag>
                    <span className="text-xs text-tertiary">
                        resolved Aug 18 ·{' '}
                        <Link to={urls.v2Report(id)} className="text-secondary" data-attr="v2-resolved-view-original">
                            view the original report
                        </Link>
                    </span>
                    <span className="flex-1" />
                    <span className="text-xs text-tertiary">
                        Report → Launch → Monitor → <strong className="text-primary">Resolve</strong>
                    </span>
                    <LemonButton type="secondary" onClick={copyPageLink} data-attr="v2-resolved-share">
                        Share
                    </LemonButton>
                </div>

                <div className="flex rounded-lg border border-primary bg-surface-primary max-lg:flex-col">
                    <aside className="flex w-[400px] flex-none flex-col gap-5 border-r border-primary p-5 max-lg:w-auto max-lg:border-r-0 max-lg:border-b">
                        <div className="flex flex-col gap-1">
                            <Microlabel>Observation</Microlabel>
                            <div className="mt-1 flex items-center gap-2 text-xs text-secondary">
                                <span className="h-1.5 w-1.5 flex-none rounded-full bg-success" />
                                <span>Wrong variant evaluations per day</span>
                            </div>
                            <div className="flex items-baseline gap-2.5">
                                <span className="font-mono text-2xl font-semibold">0/day</span>
                                <LemonTag type="success" className="font-mono">
                                    was 276/day at peak
                                </LemonTag>
                            </div>
                        </div>

                        <div className="flex flex-col gap-0.5">
                            <AnnotatedLineChart data={WRONG_VARIANT_CHART} height={130} />
                            <div className="mt-1.5 text-[11px] text-secondary">
                                Full arc: the cause deploy, the wrong variants it served, the fix, and a flat floor
                                since.
                            </div>
                        </div>

                        <LemonDivider className="my-0" />

                        <div className="flex flex-col">
                            <Microlabel>Timeline</Microlabel>
                            <div className="mt-2 flex flex-col">
                                {TIMELINE.map((row) => (
                                    <div
                                        key={row.label}
                                        className="flex items-center gap-3 border-b border-primary py-2 last:border-b-0"
                                    >
                                        <span
                                            className={`h-1.5 w-1.5 flex-none rounded-full ${DOT_COLOR[row.color]}`}
                                        />
                                        <span className="flex-1 text-[13px]">{row.label}</span>
                                        <span className="font-mono text-[11px] text-secondary">{row.time}</span>
                                        <span
                                            className={`min-w-[52px] rounded bg-surface-secondary px-1.5 py-0.5 text-center font-mono text-[11px] ${
                                                CHIP_TEXT_COLOR[row.color]
                                            }`}
                                        >
                                            {row.chip}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </aside>

                    <main className="min-w-0 max-w-[760px] flex-1 p-8">
                        <div className="mb-7 flex flex-wrap items-center gap-2.5 border-b border-primary pb-5">
                            <span className="text-sm font-semibold">Report summary</span>
                            <LemonTag type="success">reopened with results</LemonTag>
                            <span className="flex-1" />
                            <span className="text-xs text-tertiary">✦ Updated Aug 18, 07:05 UTC</span>
                        </div>

                        <div className="flex flex-col gap-11">
                            <section className="flex flex-col gap-3.5">
                                <h1 className="m-0 text-2xl leading-tight font-bold">
                                    Fixed: server-side flags respect the properties you send
                                </h1>
                                <p className="m-0 text-base leading-relaxed text-secondary">
                                    Enrichment now only fills person properties the caller did not send. Wrong variant
                                    evaluations hit 0 on Aug 11 and stayed there through the 7-day verification window.{' '}
                                    <strong className="text-primary">1,930 users recovered</strong> the variant they
                                    should have had all along.
                                </p>
                            </section>

                            <section className="flex flex-col gap-3.5">
                                <h2 className="m-0 text-lg font-semibold">What's changed since Aug 9</h2>
                                <div className="flex flex-col">
                                    {DELTAS.map((delta) => (
                                        <div
                                            key={delta.label}
                                            className="flex items-baseline gap-3.5 border-b border-primary py-2.5 last:border-b-0"
                                        >
                                            <span className="flex-1 text-sm">{delta.label}</span>
                                            <span className="font-mono text-[13px] text-tertiary line-through">
                                                {delta.was}
                                            </span>
                                            <span className="text-xs text-tertiary">→</span>
                                            <span
                                                className={`min-w-16 text-right font-mono text-[13px] font-semibold ${
                                                    delta.recovered ? 'text-success' : 'text-danger'
                                                }`}
                                            >
                                                {delta.now}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                                <p className="m-0 text-[13px] leading-relaxed text-secondary">
                                    Verified against 7 days of server-side flag calls after the fix shipped: every
                                    evaluation matched the person properties the caller sent with the request.
                                </p>
                            </section>

                            <section className="flex flex-col gap-3">
                                <h2 className="m-0 text-lg font-semibold">One thing didn't recover</h2>
                                <p className="m-0 text-[15px] leading-relaxed text-secondary">
                                    <strong className="text-primary">
                                        Support tickets have not gone back to zero yet.
                                    </strong>{' '}
                                    About one a week still comes from someone whose client cached the wrong variant
                                    before the fix. Those clear on their own as sessions expire, and this report stays
                                    linked from each ticket so support can answer in one click.
                                </p>
                                <div className="flex flex-wrap items-center gap-3.5 rounded border border-primary bg-surface-secondary p-4">
                                    <LemonTag type="highlight">New opportunity</LemonTag>
                                    <span className="flex-1 text-[13px] leading-normal text-secondary">
                                        Add a regression test that pins caller-supplied person properties over
                                        server-side enrichment, and run it for every server SDK, so this class of bug
                                        cannot ship silently again.
                                    </span>
                                    <LemonButton
                                        type="primary"
                                        size="small"
                                        onClick={() => lemonToast.info('Not part of this demo')}
                                        data-attr="v2-resolved-open-suggestion"
                                    >
                                        Open suggestion
                                    </LemonButton>
                                </div>
                            </section>

                            <section className="flex flex-col gap-3.5">
                                <div className="flex items-center gap-3">
                                    <h2 className="m-0 text-lg font-semibold text-secondary">
                                        Original report · Aug 9
                                    </h2>
                                    <span className="h-px flex-1 bg-[var(--color-border-primary)]" />
                                </div>
                                <LemonCollapse
                                    panels={[
                                        {
                                            key: 'original',
                                            dataAttr: 'v2-resolved-original-report',
                                            header: (
                                                <span className="text-[13px] font-normal text-tertiary">
                                                    Server-side flag calls that passed person properties could evaluate
                                                    the wrong variant, because GeoIP enrichment overwrote them · 1,930
                                                    users · 10 days.
                                                </span>
                                            ),
                                            content: (
                                                <div className="flex flex-col gap-2.5 py-2">
                                                    <h3 className="m-0 text-base font-bold">
                                                        GeoIP overwrote person properties sent by server SDKs.
                                                    </h3>
                                                    <p className="m-0 text-sm leading-relaxed text-secondary">
                                                        Flag calls from server SDKs can pass their own person properties
                                                        with the request. Deploy <Mono>b2d47e1</Mono> moved GeoIP
                                                        enrichment ahead of those properties, so enrichment overwrote
                                                        what the caller sent and a flag targeted on a caller-supplied
                                                        property matched the wrong rule.{' '}
                                                        <strong className="text-primary">1,930 users</strong> saw a
                                                        wrong variant over 10 days.
                                                    </p>
                                                    <p className="m-0 text-sm leading-relaxed text-secondary">
                                                        The fix reorders enrichment so it only fills properties the
                                                        caller did not send. Caller-supplied values win, and the
                                                        evaluation matches what the SDK asked for.
                                                    </p>
                                                    <Link
                                                        to={urls.v2Report(id)}
                                                        className="text-[13px]"
                                                        data-attr="v2-resolved-read-original"
                                                    >
                                                        Read the full original report →
                                                    </Link>
                                                </div>
                                            ),
                                        },
                                    ]}
                                />
                            </section>
                        </div>
                    </main>
                </div>
            </div>
        </div>
    )
}

export const scene: SceneExport<V2ResolvedSceneProps> = {
    component: V2ResolvedScene,
    paramsToProps: ({ params: { id } }) => ({ id: id ?? RESOLVED_DEMO_REPORT_ID }),
}

export default V2ResolvedScene
