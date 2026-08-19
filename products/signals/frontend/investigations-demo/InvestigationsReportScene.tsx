import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSkeleton, LemonTag, Link, lemonToast } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AnnotatedLineChart } from './components/AnnotatedLineChart'
import { CreatePrModal } from './components/CreatePrModal'
import { createPrModalLogic } from './components/createPrModalLogic'
import { DemoBarStrip } from './components/DemoBarStrip'
import { DemoDiffBlock, diffLinesFromSnippet } from './components/DemoDiffBlock'
import { SendToAgentMenu } from './components/SendToAgentMenu'
import {
    REPORT_GENERATION_STEPS,
    ReportTimelineColor,
    ReportTimelineRow,
    investigationsReportLogic,
} from './investigationsReportLogic'

const FLAG_KEY = 'checkout_token_refresh_fallback'

const AGENT_PROMPT = [
    'Fix INV-0247: TOKEN_EXPIRED at checkout (42/hr, baseline ~2/hr).',
    'Root cause: commit a3f9c21 removed the token-refresh fallback inside strict validation in PaymentTokenValidator.ts.',
    'Fix: restore the refresh fallback, keeping the strict path for genuinely unrefreshable tokens, and stop swallowing the 402 on the client.',
    'Success criteria: TOKEN_EXPIRED back under 3/hr, payment-step conversion back to 94%.',
    'Pull the full investigation with the PostHog MCP: posthog issue INV-0247.',
].join('\n')

const REMOVED_CODE_SNIPPET = `   if (token.expiresAt < Date.now()) {
-    const refreshed = await this.refreshToken(token);
-    if (refreshed) return this.validate(refreshed);
     throw new TokenValidationError('TOKEN_EXPIRED');
   }`

const VALIDATOR_FIX_SNIPPET = `   if (token.expiresAt < Date.now()) {
+    // Restore refresh fallback removed in a3f9c21 (INV-0247)
+    const refreshed = await this.refreshToken(token);
+    if (refreshed) return this.validate(refreshed);
+    metrics.increment('payments.token_refresh_failed');
     throw new TokenValidationError('TOKEN_EXPIRED');
   }`

const CHECKOUT_FIX_SNIPPET = `   } catch (err) {
-    // payment errors handled server-side
-    return;
+    setPaymentError(toUserMessage(err)); // INV-0247: never fail silently
+    telemetry.capture('checkout.payment_error_rendered', { code: err.code });
   }`

const ERROR_RATE_POINTS =
    '0,111 30,110 60,111 82,110 86,104 100,96 120,88 140,90 160,78 180,70 200,73 220,60 240,54 260,56 280,45 300,40 316,42 336,32 360,26'
const COMPARISON_POINTS =
    '0,113 30,112 60,113 82,112 90,108 110,102 135,97 165,88 195,82 225,72 255,66 285,56 315,50 345,42 360,38'
const OCCURRENCE_BARS = [3, 2, 3, 2, 4, 7, 9, 8, 12, 14, 13, 17, 19, 18, 22, 24, 23, 27, 29, 31, 30, 33, 35, 36]
const ERROR_BARS = [1, 1, 2, 1, 3, 6, 8, 7, 11, 13, 12, 16, 18, 17, 20, 22, 21, 24, 26, 28, 27, 30, 31, 32]

const TIMELINE_DOT: Record<ReportTimelineColor, string> = {
    danger: 'bg-danger',
    muted: 'bg-[var(--color-text-tertiary)]',
    success: 'bg-success',
}

const TIMELINE_CHIP_TEXT: Record<ReportTimelineColor, string> = {
    danger: 'text-danger',
    muted: 'text-secondary',
    success: 'text-success',
}

function Microlabel({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="text-[11px] font-semibold tracking-wider text-secondary uppercase">{children}</div>
}

function PulsingDot(): JSX.Element {
    return <span className="h-2 w-2 flex-none animate-pulse rounded-full bg-accent motion-reduce:animate-none" />
}

function Mono({ children }: { children: React.ReactNode }): JSX.Element {
    return <span className="font-mono text-[0.9em]">{children}</span>
}

function EvidenceCard({
    to,
    title,
    meta,
    metaClassName,
    caption,
    dataAttr,
    children,
}: {
    to: string
    title: string
    meta: string
    metaClassName?: string
    caption: string
    dataAttr: string
    children?: React.ReactNode
}): JSX.Element {
    return (
        <Link
            to={to}
            disableClientSideRouting
            className="flex flex-col gap-2 rounded border border-primary bg-surface-secondary p-3 text-primary hover:border-accent hover:text-primary hover:no-underline"
            data-attr={dataAttr}
        >
            <div className="flex items-center gap-2.5">
                <span className="flex-1 text-sm font-semibold">{title}</span>
                <span className={`font-mono text-[11px] ${metaClassName ?? 'text-secondary'}`}>{meta}</span>
            </div>
            {children}
            <div className="text-[11px] leading-normal text-secondary">{caption}</div>
        </Link>
    )
}

function EvidenceBarRow({
    label,
    percent,
    valueLabel,
    emphasized,
    baselineTickClassName,
}: {
    label: string
    percent: number
    valueLabel: string
    emphasized?: boolean
    /** Where the 28-day baseline tick sits on the bar, e.g. "left-[84%]" */
    baselineTickClassName?: string
}): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <span
                className={`w-16 flex-none text-[10px] ${emphasized ? 'font-semibold text-primary' : 'text-secondary'}`}
            >
                {label}
            </span>
            <div className="relative flex-1">
                <LemonProgress
                    percent={percent}
                    strokeColor={emphasized ? 'var(--danger)' : 'var(--color-accent)'}
                    bgColor="var(--color-bg-fill-tertiary)"
                />
                {baselineTickClassName ? (
                    <span
                        className={`absolute -top-1 h-3.5 w-0.5 bg-[var(--color-text-primary)] ${baselineTickClassName}`}
                    />
                ) : null}
            </div>
            <span
                className={`w-10 flex-none text-right font-mono text-[10px] ${
                    emphasized ? 'text-danger' : 'text-secondary'
                }`}
            >
                {valueLabel}
            </span>
        </div>
    )
}

function TimelineRow({ row }: { row: ReportTimelineRow }): JSX.Element {
    return (
        <div className="flex items-center gap-3 border-b border-primary py-2 last:border-b-0">
            <span className={`h-1.5 w-1.5 flex-none rounded-full ${TIMELINE_DOT[row.color]}`} />
            <span className="flex-1 text-[13px]">{row.label}</span>
            <span className="font-mono text-[11px] text-secondary">{row.time}</span>
            <span
                className={`min-w-[52px] rounded bg-surface-secondary px-1.5 py-0.5 text-center font-mono text-[11px] ${
                    TIMELINE_CHIP_TEXT[row.color]
                }`}
            >
                {row.chip}
            </span>
        </div>
    )
}

function MetricTile({
    id,
    label,
    value,
    valueClassName,
    footnote,
    footnoteClassName,
}: {
    id: string
    label: string
    value: string
    valueClassName?: string
    footnote: string
    footnoteClassName?: string
}): JSX.Element {
    return (
        <div id={id} className="flex flex-col gap-1 rounded border border-primary bg-surface-secondary p-3.5">
            <span className="text-[11px] tracking-wide text-secondary uppercase">{label}</span>
            <span className={`font-mono text-xl font-semibold ${valueClassName ?? ''}`}>{value}</span>
            <span className={`font-mono text-[11px] ${footnoteClassName ?? 'text-secondary'}`}>{footnote}</span>
        </div>
    )
}

function NumberedClaim({ index, children }: { index: number; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-baseline gap-3.5">
            <span className="w-4 flex-none font-mono text-[11px] font-semibold text-secondary">{index}</span>
            <p className="m-0 text-[15px] leading-relaxed text-secondary">{children}</p>
        </div>
    )
}

function CriteriaRow({
    icon,
    iconClassName,
    label,
    value,
    valueClassName,
}: {
    icon: string
    iconClassName: string
    label: string
    value: string
    valueClassName: string
}): JSX.Element {
    return (
        <div className="flex items-center gap-2.5 border-b border-primary py-2.5 last:border-b-0">
            <span
                className={`inline-flex h-4 w-4 flex-none items-center justify-center rounded-full text-[9px] font-bold ${iconClassName}`}
            >
                {icon}
            </span>
            <span className="flex-1 text-[13px]">{label}</span>
            <span className={`font-mono text-xs font-semibold ${valueClassName}`}>{value}</span>
        </div>
    )
}

function GenerationChecklist({ step }: { step: number }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 rounded border border-primary bg-surface-secondary p-4">
            <div className="flex items-center gap-2">
                <PulsingDot />
                <span className="font-mono text-[10px] tracking-wider text-accent uppercase">
                    Generating the code change
                </span>
            </div>
            {REPORT_GENERATION_STEPS.map((label, index) => {
                const done = index < step
                const current = index === step
                return (
                    <div
                        key={label}
                        className={`flex items-center gap-2.5 text-[13px] ${
                            done ? 'text-success' : current ? 'text-primary' : 'text-tertiary'
                        } ${current ? 'animate-pulse motion-reduce:animate-none' : ''}`}
                    >
                        <span className="w-3.5 flex-none font-mono text-[11px]">
                            {done ? '✓' : current ? '●' : '·'}
                        </span>
                        <span>{label}</span>
                    </div>
                )
            })}
        </div>
    )
}

export function InvestigationsReportScene(): JSX.Element {
    const { phase, generationStep, agentName, prModalOpen, codeOpen, evidenceExpanded, timeline } =
        useValues(investigationsReportLogic)
    const { startGeneration, sendToAgent, launch, setPrModalOpen, toggleCode, toggleEvidence } =
        useActions(investigationsReportLogic)
    const { model, effort } = useValues(createPrModalLogic)

    const showChanges = phase === 'proposed' || phase === 'committed' || phase === 'launched'
    const changesTitle =
        phase === 'proposed' ? 'Generated changes' : phase === 'committed' ? 'Changes from the commit' : 'Changes made'
    const committedByAgent = !!agentName && (phase === 'committed' || phase === 'launched')

    return (
        <div className="mx-auto flex w-full max-w-[1360px] flex-col gap-4 p-4 lg:p-7">
            <div className="flex">
                <Link
                    to={urls.investigationsDemo()}
                    className="text-xs text-secondary"
                    data-attr="investigations-demo-report-back"
                >
                    ← Inbox
                </Link>
            </div>

            {phase === 'launched' ? (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Open fix monitor →',
                        to: urls.investigationsDemoMonitor(),
                        'data-attr': 'investigations-demo-report-open-monitor',
                    }}
                >
                    <span className="text-sm font-normal">The fix is live and being monitored.</span>
                </LemonBanner>
            ) : null}

            <div className="flex rounded-lg border border-primary bg-surface-primary max-lg:flex-col">
                <aside className="flex w-[400px] flex-none flex-col gap-5 border-r border-primary p-5 max-lg:w-auto max-lg:border-r-0 max-lg:border-b">
                    <div className="flex flex-col gap-1">
                        <Microlabel>Observation</Microlabel>
                        <div className="flex items-baseline gap-2.5">
                            <span className="font-mono text-2xl font-semibold">42/hr</span>
                            <LemonTag type="danger" className="font-mono">
                                baseline ≈2/hr
                            </LemonTag>
                        </div>
                    </div>

                    <div className="flex flex-col gap-0.5">
                        <AnnotatedLineChart
                            viewWidth={360}
                            viewHeight={130}
                            series={[
                                { points: ERROR_RATE_POINTS, color: 'accent' },
                                { points: COMPARISON_POINTS, color: 'muted', dashed: true, strokeWidth: 1.2 },
                            ]}
                            annotations={[
                                { x: 86, label: 'deploy a3f9c21', color: 'danger' },
                                { x: 284, label: 'detected', color: 'muted', labelAnchor: 'end' },
                            ]}
                            baselineY={112}
                        />
                        <DemoBarStrip values={OCCURRENCE_BARS} alarmFromIndex={5} />
                        <div className="flex justify-between font-mono text-[10px] text-tertiary">
                            <span>Aug 13</span>
                            <span>Aug 14</span>
                            <span>Aug 15</span>
                            <span>Aug 16</span>
                            <span>Aug 17</span>
                        </div>
                    </div>

                    <LemonDivider className="my-0" />

                    <div className="flex flex-col gap-2.5">
                        <Microlabel>Evidence</Microlabel>

                        <EvidenceCard
                            to="#replay"
                            title="Session replays"
                            meta="214 matching"
                            caption="Three silent Pay taps, no error rendered, session ends. Same pattern in all 214."
                            dataAttr="investigations-demo-report-evidence-replays"
                        >
                            <div className="flex items-center gap-2">
                                <span className="font-mono text-[10px] text-tertiary">0:31</span>
                                <div className="relative h-1 flex-1 rounded-sm bg-fill-tertiary">
                                    <div className="absolute top-0 left-0 h-full w-[70%] rounded-sm bg-[var(--color-text-tertiary)]" />
                                    <span className="absolute -top-1 left-[58%] h-2.5 w-0.5 bg-danger" />
                                    <span className="absolute -top-1 left-[66%] h-2.5 w-0.5 bg-danger" />
                                    <span className="absolute -top-1 left-[74%] h-2.5 w-0.5 bg-danger" />
                                </div>
                                <span className="font-mono text-[10px] text-tertiary">0:47</span>
                            </div>
                        </EvidenceCard>

                        <EvidenceCard
                            to="#claims"
                            title="Errors"
                            meta="4,312 events"
                            caption="TOKEN_EXPIRED, one error group. First seen 4 minutes after the deploy, still climbing."
                            dataAttr="investigations-demo-report-evidence-errors"
                        >
                            <DemoBarStrip values={ERROR_BARS} alarmFromIndex={5} height={34} barWidth={8} gap={5.4} />
                        </EvidenceCard>

                        <EvidenceCard
                            to="#m-conv"
                            title="Behavioral data"
                            meta="−12% conv."
                            metaClassName="text-danger"
                            caption="Returning-user funnel against the 28-day baseline (tick). The drop is isolated to the payment step."
                            dataAttr="investigations-demo-report-evidence-funnel"
                        >
                            <div className="flex flex-col gap-1.5">
                                <EvidenceBarRow label="Cart" percent={100} valueLabel="100%" />
                                <EvidenceBarRow label="Shipping" percent={91} valueLabel="91%" />
                                <EvidenceBarRow
                                    label="Payment"
                                    percent={72}
                                    valueLabel="72%"
                                    emphasized
                                    baselineTickClassName="left-[84%]"
                                />
                                <EvidenceBarRow label="Confirm" percent={70} valueLabel="70%" />
                            </div>
                        </EvidenceCard>

                        {evidenceExpanded ? (
                            <>
                                <EvidenceCard
                                    to="#claims"
                                    title="Commit diff"
                                    meta="a3f9c21"
                                    caption="Removed the token-refresh fallback that previously rescued expired tokens."
                                    dataAttr="investigations-demo-report-evidence-commit"
                                >
                                    <DemoDiffBlock
                                        className="text-[10px] leading-5"
                                        lines={diffLinesFromSnippet(
                                            `- const refreshed = await this.refreshToken(token);\n- if (refreshed) return this.validate(refreshed);\n  throw new TokenValidationError('TOKEN_EXPIRED');`
                                        )}
                                    />
                                </EvidenceCard>
                                <EvidenceCard
                                    to="#claims"
                                    title="Isolation query"
                                    meta="99.8% fail"
                                    metaClassName="text-danger"
                                    caption="Failure rate by token status since the deploy. Only expired tokens fail."
                                    dataAttr="investigations-demo-report-evidence-isolation"
                                >
                                    <div className="flex flex-col gap-1.5">
                                        <EvidenceBarRow label="expired" percent={99.8} valueLabel="99.8%" emphasized />
                                        <EvidenceBarRow label="valid" percent={2} valueLabel="0.2%" />
                                        <EvidenceBarRow label="new card" percent={3} valueLabel="0.3%" />
                                    </div>
                                </EvidenceCard>
                                <EvidenceCard
                                    to="#m-users"
                                    title="Support tickets"
                                    meta="6 matching"
                                    caption="Zendesk #48112 · Aug 15 · five more describe the same silent failure."
                                    dataAttr="investigations-demo-report-evidence-tickets"
                                >
                                    <div className="text-xs leading-normal italic">
                                        “Tried to pay three times, the button does nothing. I gave up and ordered
                                        somewhere else.”
                                    </div>
                                </EvidenceCard>
                            </>
                        ) : null}

                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={toggleEvidence}
                            className="self-start"
                            data-attr="investigations-demo-report-toggle-evidence"
                        >
                            {evidenceExpanded ? 'Show less' : 'Show 3 more'}
                        </LemonButton>
                    </div>

                    <LemonDivider className="my-0" />

                    <div className="flex flex-col">
                        <Microlabel>Timeline</Microlabel>
                        <div className="mt-2 flex flex-col">
                            {timeline.map((row) => (
                                <TimelineRow key={row.label} row={row} />
                            ))}
                        </div>
                    </div>
                </aside>

                <main className="min-w-0 max-w-[760px] flex-1 p-8">
                    <div className="mb-7 flex items-center gap-2.5 border-b border-primary pb-5">
                        <span className="text-sm font-semibold">Report summary</span>
                        <span className="flex-1" />
                        <span className="text-xs text-tertiary">✦ Generated Aug 16, 15:03 UTC</span>
                    </div>

                    <div className="flex flex-col gap-11">
                        <section className="flex flex-col gap-3.5">
                            <h1 className="m-0 text-2xl leading-tight font-bold">
                                Checkout silently fails for returning users with expired saved cards.
                            </h1>
                            <p className="m-0 text-base leading-relaxed text-secondary">
                                <strong className="text-primary">1,847 users</strong> hit a Pay button that does nothing
                                in the last 72 hours, growing by about 600 a week. The failure began four minutes after
                                deploy <Mono>a3f9c21</Mono> and is invisible to users: no error, no spinner, no path
                                forward except leaving.
                            </p>
                        </section>

                        <section className="flex flex-col gap-3">
                            <h2 className="m-0 text-lg font-semibold">Problem</h2>
                            <p className="m-0 text-[15px] leading-relaxed text-secondary">
                                When a returning customer pays with a saved card whose payment token has expired, the
                                checkout request fails server-side, but the client swallows the error. Deploy{' '}
                                <Mono>a3f9c21</Mono> (Aug 14, 09:12 UTC) introduced strict token validation and removed
                                the token-refresh fallback that previously rescued expired tokens transparently.
                            </p>
                            <figure
                                id="replay"
                                className="m-0 mt-1 overflow-hidden rounded border border-primary bg-surface-secondary"
                            >
                                <div className="flex items-center gap-2.5 border-b border-primary px-3.5 py-2 font-mono text-[11px] text-secondary">
                                    <span className="h-1.5 w-1.5 flex-none rounded-full bg-success" />
                                    <span>session 8f42…9c1 · iOS Safari 17 · 1 of 214 similar</span>
                                    <span className="flex-1" />
                                    <Link
                                        onClick={() => lemonToast.info('Not part of this demo')}
                                        className="text-[11px]"
                                        data-attr="investigations-demo-report-open-replay"
                                    >
                                        Open replay ↗
                                    </Link>
                                </div>
                                <div className="px-4 py-3.5 text-sm leading-relaxed text-secondary">
                                    User taps <em className="text-primary">Pay $86.40</em> three times between 0:31 and
                                    0:47. Nothing renders: no error state, no network retry. The session ends at 0:47.
                                    All 214 matching replays show the same pattern.
                                </div>
                            </figure>
                        </section>

                        <section className="flex flex-col gap-3.5">
                            <h2 className="m-0 text-lg font-semibold">Impact</h2>
                            <div className="grid grid-cols-3 gap-2.5 max-lg:grid-cols-1">
                                <MetricTile
                                    id="m-users"
                                    label="Users · 72h"
                                    value="1,847"
                                    footnote="+600/wk"
                                    footnoteClassName="text-danger"
                                />
                                <MetricTile
                                    id="m-conv"
                                    label="Conversion"
                                    value="−12%"
                                    valueClassName="text-danger"
                                    footnote="84% → 72%"
                                />
                                <MetricTile
                                    id="m-gmv"
                                    label="GMV at risk · wk"
                                    value="$38–52K"
                                    footnote="range, not point"
                                />
                            </div>
                            <p className="m-0 text-[15px] leading-relaxed text-secondary">
                                Every affected user is a returning customer with a saved card. 61% are on iOS Safari,
                                where saved-card usage concentrates. 31 accounts exceed $1K lifetime spend. Six Zendesk
                                tickets match the pattern, and the representative one reads:{' '}
                                <em>
                                    “Tried to pay three times, the button does nothing. I gave up and ordered somewhere
                                    else.”
                                </em>
                            </p>
                        </section>

                        <section id="claims" className="flex flex-col gap-4">
                            <h2 className="m-0 text-lg font-semibold">How we know</h2>
                            <div className="flex flex-col gap-2.5">
                                <NumberedClaim index={1}>
                                    <strong className="text-primary">The failures began with the deploy.</strong> The
                                    first TOKEN_EXPIRED failure was recorded 4 minutes after <Mono>a3f9c21</Mono>{' '}
                                    shipped, and the commit diff removes the exact code path that handled this case.
                                </NumberedClaim>
                                <NumberedClaim index={2}>
                                    <strong className="text-primary">
                                        Failures are isolated to expired saved-card tokens.
                                    </strong>{' '}
                                    99.8% failure rate for expired tokens against 0.2 to 0.3% for every other payment
                                    path, measured directly on checkout attempts since the deploy.
                                </NumberedClaim>
                                <NumberedClaim index={3}>
                                    <strong className="text-primary">The failure is silent by construction.</strong> The
                                    client catch block at <Mono>CheckoutForm.tsx:167</Mono> discards the 402 response
                                    with no UI state change.
                                </NumberedClaim>
                            </div>
                            {codeOpen ? (
                                <DemoDiffBlock
                                    title="commit a3f9c21 · src/payments/PaymentTokenValidator.ts"
                                    lines={diffLinesFromSnippet(REMOVED_CODE_SNIPPET)}
                                />
                            ) : null}
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={toggleCode}
                                className="self-start"
                                data-attr="investigations-demo-report-toggle-code"
                            >
                                {codeOpen ? 'Hide diff' : 'Show the removed code path'}
                            </LemonButton>
                            <p className="m-0 text-[13px] leading-relaxed text-secondary">
                                Ruled out: payment-provider outage (status green, and failures precede any provider
                                call), iOS client bug (the errors originate server-side), experiment interference
                                (uniform across variants).
                            </p>
                        </section>

                        <section id="fix" className="flex flex-col gap-3">
                            <h2 className="m-0 text-lg font-semibold">Fix</h2>
                            <p className="m-0 text-[15px] leading-relaxed text-secondary">
                                Restore the token-refresh fallback inside strict validation (+4 lines in{' '}
                                <Mono>PaymentTokenValidator.ts</Mono>), keeping the strict path for genuinely
                                unrefreshable tokens. Immediate mitigation: turn the{' '}
                                <Mono>strict_token_validation</Mono> flag off to restore the legacy path now.
                            </p>

                            {phase === 'reported' ? (
                                <div className="flex flex-wrap items-center gap-2">
                                    <LemonButton
                                        type="primary"
                                        onClick={() => setPrModalOpen(true)}
                                        data-attr="investigations-demo-report-fix-and-monitor"
                                    >
                                        Fix &amp; monitor
                                    </LemonButton>
                                    <SendToAgentMenu promptText={AGENT_PROMPT} onSelectAgent={sendToAgent}>
                                        <LemonButton
                                            type="secondary"
                                            sideIcon={<IconChevronDown />}
                                            data-attr="investigations-demo-report-send-to-agent"
                                        >
                                            Send to my agent
                                        </LemonButton>
                                    </SendToAgentMenu>
                                </div>
                            ) : null}

                            {phase === 'generating' ? <GenerationChecklist step={generationStep} /> : null}

                            {phase === 'sent' ? (
                                <div className="flex flex-col gap-2.5 rounded border border-primary bg-surface-secondary p-4">
                                    <div className="flex items-center gap-2">
                                        <PulsingDot />
                                        <span className="font-mono text-[10px] tracking-wider text-accent uppercase">
                                            Handed off to {agentName}
                                        </span>
                                    </div>
                                    <div className="text-[13px] leading-relaxed text-secondary">
                                        Branch <Mono>fix/inv-0247</Mono> created with the full investigation attached:
                                        root cause, evidence links, success criteria. This report is watching GitHub and
                                        will pick up the commit when it lands.
                                    </div>
                                    <LemonSkeleton className="h-1 max-w-[420px]" />
                                </div>
                            ) : null}

                            {phase === 'committed' ? (
                                <div className="flex flex-col gap-2.5 rounded border border-success bg-surface-primary p-4">
                                    <div className="flex items-center gap-2">
                                        <span className="inline-flex h-3.5 w-3.5 flex-none items-center justify-center rounded-full bg-fill-success-highlight text-[8px] font-bold text-success">
                                            ✓
                                        </span>
                                        <span className="font-mono text-[10px] tracking-wider text-success uppercase">
                                            Commit detected on fix/inv-0247
                                        </span>
                                    </div>
                                    <div className="text-[13px] leading-relaxed text-secondary">
                                        <Mono>9d2e4b7</Mono> pushed via {agentName} 12 minutes ago, 2 files, +9 −2. The
                                        diff matches the recommended fix and is shown below. Nothing has shipped yet:
                                        launching still runs it behind the flag with monitoring.
                                    </div>
                                    <div className="flex flex-wrap items-center gap-3">
                                        <LemonButton
                                            type="primary"
                                            onClick={launch}
                                            data-attr="investigations-demo-report-launch-from-commit"
                                        >
                                            Launch experiment &amp; monitor
                                        </LemonButton>
                                        <Link
                                            onClick={() => lemonToast.info('Not part of this demo')}
                                            className="text-[13px]"
                                            data-attr="investigations-demo-report-view-commit"
                                        >
                                            View commit on GitHub ↗
                                        </Link>
                                    </div>
                                </div>
                            ) : null}

                            {phase === 'launched' ? (
                                <p className="m-0 text-[13px] leading-relaxed text-success">
                                    ✓ Launched Aug 18 behind <Mono>{FLAG_KEY}</Mono>. Live results are in the monitoring
                                    section below, day 1 of 7.
                                </p>
                            ) : null}
                        </section>

                        {showChanges ? (
                            <section id="changes" className="flex flex-col gap-4">
                                <div className="flex flex-col gap-2">
                                    <div className="flex flex-wrap items-center gap-2.5">
                                        <h2 className="m-0 text-lg font-semibold">{changesTitle}</h2>
                                        {phase !== 'committed' ? (
                                            <Link
                                                onClick={() => lemonToast.info('Not part of this demo')}
                                                className="font-mono text-[11px] font-semibold"
                                                data-attr="investigations-demo-report-view-pr"
                                            >
                                                {phase === 'proposed' ? 'draft PR #4821 on GitHub ↗' : 'PR #4821 ↗'}
                                            </Link>
                                        ) : null}
                                    </div>
                                    <div className="flex flex-wrap items-center gap-2.5 font-mono text-[11px] text-secondary">
                                        {committedByAgent ? <span>fix/inv-0247 · 9d2e4b7 ·</span> : null}
                                        <span>
                                            <span className="font-semibold text-success">+9</span>{' '}
                                            <span className="font-semibold text-danger">−2</span> · 2 files
                                        </span>
                                        <span className="rounded-full border border-primary bg-surface-secondary px-2 py-0.5 text-[10.5px]">
                                            {agentName ? `via ${agentName}` : `✦ ${model} · ${effort} effort`}
                                        </span>
                                    </div>
                                </div>

                                <div className="flex flex-col gap-2.5">
                                    <NumberedClaim index={1}>
                                        <strong className="text-primary">
                                            Restore the refresh fallback inside strict validation.
                                        </strong>{' '}
                                        Expired tokens get one transparent refresh attempt before failing, the exact
                                        path a3f9c21 removed. Strict validation is preserved: genuinely unrefreshable
                                        tokens still throw.
                                    </NumberedClaim>
                                    <DemoDiffBlock
                                        className="ml-7"
                                        title="src/payments/PaymentTokenValidator.ts"
                                        lines={diffLinesFromSnippet(VALIDATOR_FIX_SNIPPET)}
                                    />
                                    <p className="m-0 mb-1.5 ml-7 text-[13px] leading-relaxed text-secondary">
                                        The metrics line makes the failure class observable. A refresh that fails now
                                        increments a counter instead of vanishing, so a regression here alerts within
                                        minutes rather than surfacing as a conversion drop days later.
                                    </p>

                                    <NumberedClaim index={2}>
                                        <strong className="text-primary">Stop swallowing the 402 on the client.</strong>{' '}
                                        The catch block at <Mono>CheckoutForm.tsx:167</Mono> discarded payment errors
                                        with no UI change, the half of the bug that made it silent. Even with the server
                                        fixed, any future payment failure must render.
                                    </NumberedClaim>
                                    <DemoDiffBlock
                                        className="ml-7"
                                        title="src/checkout/CheckoutForm.tsx:167"
                                        lines={diffLinesFromSnippet(CHECKOUT_FIX_SNIPPET)}
                                    />
                                    <p className="m-0 ml-7 text-[13px] leading-relaxed text-secondary">
                                        Considered and rejected: retrying the charge client-side (it risks
                                        double-charging on ambiguous failures) and turning{' '}
                                        <Mono>strict_token_validation</Mono> off permanently (it leaves the validation
                                        gap a3f9c21 was written to close).
                                    </p>
                                </div>

                                {phase === 'proposed' ? (
                                    <div className="flex flex-wrap items-center gap-2 border-t border-primary pt-4">
                                        <LemonButton
                                            type="primary"
                                            onClick={launch}
                                            data-attr="investigations-demo-report-approve-and-launch"
                                        >
                                            Approve &amp; launch experiment
                                        </LemonButton>
                                        <LemonButton
                                            type="secondary"
                                            onClick={() => lemonToast.info('Not part of this demo')}
                                            data-attr="investigations-demo-report-revise"
                                        >
                                            ✦ Ask PostHog AI to revise…
                                        </LemonButton>
                                        <SendToAgentMenu
                                            promptText={AGENT_PROMPT}
                                            onSelectAgent={sendToAgent}
                                            placement="top-end"
                                        >
                                            <LemonButton
                                                type="secondary"
                                                sideIcon={<IconChevronDown />}
                                                data-attr="investigations-demo-report-send-diff-to-agent"
                                            >
                                                Send to my agent
                                            </LemonButton>
                                        </SendToAgentMenu>
                                    </div>
                                ) : null}
                            </section>
                        ) : null}

                        {phase === 'launched' ? (
                            <section id="monitor-inline" className="flex flex-col gap-3.5">
                                <div className="flex flex-wrap items-center gap-2.5">
                                    <h2 className="m-0 text-lg font-semibold">Monitoring</h2>
                                    <LemonTag type="primary">Day 1 of 7 · auto-halt armed</LemonTag>
                                    <span className="flex-1" />
                                    <Link
                                        to={urls.investigationsDemoMonitor()}
                                        className="text-[13px] font-semibold"
                                        data-attr="investigations-demo-report-open-full-monitor"
                                    >
                                        Open full monitor →
                                    </Link>
                                </div>
                                <div className="flex flex-col gap-2 rounded border border-primary bg-surface-secondary p-4">
                                    <div className="flex items-baseline gap-2.5">
                                        <span className="font-mono text-xs text-secondary">{FLAG_KEY}</span>
                                        <span className="flex-1" />
                                        <span className="font-mono text-lg font-semibold">10%</span>
                                    </div>
                                    <LemonProgress percent={10} strokeColor="var(--color-accent)" />
                                    <div className="flex justify-between font-mono text-[11px] text-secondary">
                                        <span className="font-semibold text-accent">10% · Aug 18 ← now</span>
                                        <span>50% · Aug 19</span>
                                        <span>100% · Aug 21</span>
                                    </div>
                                </div>
                                <div className="flex flex-col">
                                    <CriteriaRow
                                        icon="●"
                                        iconClassName="bg-fill-info-highlight text-accent"
                                        label="Error rate back to baseline (target ≤ 2/hr)"
                                        value="2.4/hr ↓ treated cohort"
                                        valueClassName="text-accent"
                                    />
                                    <CriteriaRow
                                        icon="✓"
                                        iconClassName="bg-fill-success-highlight text-success"
                                        label="No new matching tickets"
                                        value="0 so far"
                                        valueClassName="text-success"
                                    />
                                    <CriteriaRow
                                        icon="…"
                                        iconClassName="bg-surface-secondary text-secondary"
                                        label="Conversion recovers to ≥ 84%"
                                        value="needs 100% ramp"
                                        valueClassName="text-secondary"
                                    />
                                </div>
                            </section>
                        ) : null}
                    </div>
                </main>
            </div>

            <CreatePrModal
                isOpen={prModalOpen}
                flagKey={FLAG_KEY}
                monitoringCriteria="errors ≤ 2/hr, conversion ≥ 84%, no new tickets"
                onClose={() => setPrModalOpen(false)}
                onConfirm={startGeneration}
            />
        </div>
    )
}

export const scene: SceneExport = { component: InvestigationsReportScene, logic: investigationsReportLogic }

export default InvestigationsReportScene
