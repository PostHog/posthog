import { LemonButton, LemonCollapse, LemonDivider, LemonTag, Link, lemonToast } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AnnotatedLineChart } from './components/AnnotatedLineChart'
import { DEMO_REPORT_ID } from './mockData'

const RECOVERY_POINTS =
    '0,111 20,110 34,70 60,45 90,32 120,26 150,24 176,23 190,60 210,66 224,96 250,106 280,110 310,111 340,111 360,111'

type ResolvedRowColor = 'danger' | 'muted' | 'success'

const DOT_COLOR: Record<ResolvedRowColor, string> = {
    danger: 'bg-danger',
    muted: 'bg-[var(--color-text-tertiary)]',
    success: 'bg-success',
}

const CHIP_TEXT_COLOR: Record<ResolvedRowColor, string> = {
    danger: 'text-danger',
    muted: 'text-secondary',
    success: 'text-success',
}

const TIMELINE: { label: string; time: string; chip: string; color: ResolvedRowColor }[] = [
    { label: 'Deploy ships strict validation', time: 'Aug 14', chip: 'a3f9c21', color: 'danger' },
    { label: 'Anomaly detected, report published', time: 'Aug 16', chip: 'v1', color: 'muted' },
    { label: 'Fix launched behind flag at 10%', time: 'Aug 18', chip: '#4821', color: 'success' },
    { label: 'Ramped to 100%, guardrails clean', time: 'Aug 21', chip: '100%', color: 'success' },
    { label: 'All criteria held 7 days', time: 'Aug 25', chip: '3/3', color: 'success' },
    { label: 'Report updated · resolved', time: 'Aug 25', chip: 'v2', color: 'success' },
]

const DELTAS: { label: string; was: string; now: string; recovered: boolean }[] = [
    { label: 'TOKEN_EXPIRED error rate', was: '42/hr', now: '1.9/hr', recovered: true },
    { label: 'Returning-user conversion', was: '72%', now: '83.7%', recovered: true },
    { label: 'Users hitting the failure', was: '+600/wk', now: '0 since Aug 21', recovered: true },
    { label: 'Matching support tickets', was: '6', now: '0 new', recovered: true },
    { label: 'Affected users who returned', was: 'n/a', now: '635 of 1,847', recovered: false },
]

function Microlabel({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="text-[11px] font-semibold tracking-wider text-secondary uppercase">{children}</div>
}

function Mono({ children }: { children: React.ReactNode }): JSX.Element {
    return <span className="font-mono text-[0.9em]">{children}</span>
}

export function InvestigationsResolvedScene(): JSX.Element {
    const copyPageLink = (): void => {
        navigator.clipboard?.writeText(window.location.href).catch(() => {})
        lemonToast.success('Link copied to clipboard')
    }

    return (
        <div className="mx-auto flex w-full max-w-[1360px] flex-col gap-4 p-4 lg:p-7">
            <div className="flex flex-wrap items-center gap-3.5">
                <Link
                    to={urls.investigationsDemo()}
                    className="text-xs text-secondary"
                    data-attr="investigations-demo-resolved-back"
                >
                    ← Investigations
                </Link>
                <span className="text-[15px] font-bold">INV-0247 · Checkout</span>
                <LemonTag type="success">Resolved</LemonTag>
                <span className="text-xs text-tertiary">
                    v2 · updated Aug 25 ·{' '}
                    <Link
                        to={urls.investigationsDemoReport(DEMO_REPORT_ID)}
                        className="text-secondary"
                        data-attr="investigations-demo-resolved-view-v1"
                    >
                        view v1
                    </Link>
                </span>
                <span className="flex-1" />
                <span className="text-xs text-tertiary">
                    Report → Launch → Monitor → <strong className="text-primary">Resolve</strong>
                </span>
                <LemonButton type="secondary" onClick={copyPageLink} data-attr="investigations-demo-resolved-share">
                    Share
                </LemonButton>
            </div>

            <div className="flex rounded-lg border border-primary bg-surface-primary max-lg:flex-col">
                <aside className="flex w-[400px] flex-none flex-col gap-5 border-r border-primary p-5 max-lg:w-auto max-lg:border-r-0 max-lg:border-b">
                    <div className="flex flex-col gap-1">
                        <Microlabel>Observation</Microlabel>
                        <div className="mt-1 flex items-center gap-2 text-xs text-secondary">
                            <span className="h-1.5 w-1.5 flex-none rounded-full bg-success" />
                            <span>TOKEN_EXPIRED errors per hour</span>
                        </div>
                        <div className="flex items-baseline gap-2.5">
                            <span className="font-mono text-2xl font-semibold">1.9/hr</span>
                            <LemonTag type="success" className="font-mono">
                                at baseline · 7 days
                            </LemonTag>
                        </div>
                    </div>

                    <div className="flex flex-col gap-0.5">
                        <AnnotatedLineChart
                            viewWidth={360}
                            viewHeight={130}
                            series={[{ points: RECOVERY_POINTS, color: 'accent' }]}
                            annotations={[
                                { x: 34, label: 'deploy a3f9c21', color: 'danger' },
                                { x: 190, label: 'fix 10%', color: 'success' },
                                { x: 250, label: '100%', color: 'success' },
                            ]}
                            baselineY={112}
                            xLabels={['Aug 14', 'Aug 17', 'Aug 20', 'Aug 23', 'Aug 25']}
                        />
                        <div className="mt-1.5 text-[11px] text-secondary">
                            Full incident arc: regression, detection, ramped fix, recovery.
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
                                    <span className={`h-1.5 w-1.5 flex-none rounded-full ${DOT_COLOR[row.color]}`} />
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
                        <span className="text-xs text-tertiary">✦ Updated Aug 25, 09:14 UTC</span>
                    </div>

                    <div className="flex flex-col gap-11">
                        <section className="flex flex-col gap-3.5">
                            <h1 className="m-0 text-2xl leading-tight font-bold">
                                Fixed. Checkout works again for returning users with expired saved cards.
                            </h1>
                            <p className="m-0 text-base leading-relaxed text-secondary">
                                PR <Mono>#4821</Mono> restored the token-refresh fallback behind flag{' '}
                                <Mono>checkout_token_refresh_fallback</Mono>, ramped 10% → 100% over 3 days. All three
                                success criteria have now held for 7 days.
                            </p>
                        </section>

                        <section className="flex flex-col gap-3.5">
                            <h2 className="m-0 text-lg font-semibold">What's changed since Aug 16</h2>
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
                                Verified by the 50/50 experiment during rollout (fallback cohort 1.8/hr, control
                                41.2/hr, above 99.9% confidence) and by 187 survey responses from affected users, 92% of
                                whom confirmed that payment now works.
                            </p>
                        </section>

                        <section className="flex flex-col gap-3">
                            <h2 className="m-0 text-lg font-semibold">One thing didn't recover</h2>
                            <p className="m-0 text-[15px] leading-relaxed text-secondary">
                                <strong className="text-primary">
                                    1,212 of the 1,847 affected users haven't attempted checkout since.
                                </strong>{' '}
                                They hit the silent failure, left, and never came back. The fix cannot reach users who
                                stopped trying. Their historical purchase cadence suggests about $21K a month of
                                run-rate at risk of quietly churning.
                            </p>
                            <div className="flex flex-wrap items-center gap-3.5 rounded border border-primary bg-surface-secondary p-4">
                                <LemonTag type="highlight">New opportunity</LemonTag>
                                <span className="flex-1 text-[13px] leading-normal text-secondary">
                                    Winback: apology email plus a one-tap re-checkout link to the 1,212 lapsed users,
                                    sent as a holdout experiment to measure recovered revenue.
                                </span>
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    onClick={() => lemonToast.info('Not part of this demo')}
                                    data-attr="investigations-demo-resolved-open-suggestion"
                                >
                                    Open suggestion
                                </LemonButton>
                            </div>
                        </section>

                        <section className="flex flex-col gap-3.5">
                            <div className="flex items-center gap-3">
                                <h2 className="m-0 text-lg font-semibold text-secondary">Original report · Aug 16</h2>
                                <span className="h-px flex-1 bg-[var(--color-border-primary)]" />
                            </div>
                            <LemonCollapse
                                panels={[
                                    {
                                        key: 'v1',
                                        dataAttr: 'investigations-demo-resolved-original-report',
                                        header: (
                                            <span className="text-[13px] font-normal text-tertiary">
                                                Silent checkout failure for expired saved-card tokens, introduced by
                                                deploy a3f9c21 · 1,847 users · −12% conversion · $38–52K/wk at risk.
                                            </span>
                                        ),
                                        content: (
                                            <div className="flex flex-col gap-2.5 py-2">
                                                <h3 className="m-0 text-base font-bold">
                                                    Checkout silently fails for returning users with expired saved
                                                    cards.
                                                </h3>
                                                <p className="m-0 text-sm leading-relaxed text-secondary">
                                                    <strong className="text-primary">1,847 users</strong> hit a Pay
                                                    button that does nothing in 72 hours. Deploy <Mono>a3f9c21</Mono>{' '}
                                                    introduced strict token validation and removed the refresh fallback,
                                                    and the client swallowed the resulting 402 with no UI change.
                                                    Failures were isolated to expired saved-card tokens (99.8% against
                                                    0.2%), returning-user conversion fell 12 points, and $38–52K a week
                                                    of GMV was at risk.
                                                </p>
                                                <Link
                                                    to={urls.investigationsDemoReport(DEMO_REPORT_ID)}
                                                    className="text-[13px]"
                                                    data-attr="investigations-demo-resolved-read-v1"
                                                >
                                                    Read the full v1 report →
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
    )
}

export const scene: SceneExport = { component: InvestigationsResolvedScene }

export default InvestigationsResolvedScene
