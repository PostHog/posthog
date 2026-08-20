import { useActions, useValues } from 'kea'

import { IconChevronDown, IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSkeleton, LemonTag, Link, lemonToast } from '@posthog/lemon-ui'

import { resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { V2_REPORT_PANEL_OPTION } from '~/layout/navigation-3000/sidepanel/panels/max/SidePanelMax'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { AnnotatedLineChart } from './components/AnnotatedLineChart'
import { CreatePrModal } from './components/CreatePrModal'
import { createPrModalLogic } from './components/createPrModalLogic'
import { DemoBarStrip } from './components/DemoBarStrip'
import { DemoDiffBlock, diffLinesFromSnippet } from './components/DemoDiffBlock'
import { EvidenceScreenshot } from './components/EvidenceScreenshot'
import { InboxBackButton } from './components/InboxBackButton'
import { SendToAgentMenu } from './components/SendToAgentMenu'
import { DEMO_REPORT_ID } from './mockData'
import { ReportEvidenceCard, ReportImpactTile, ReportTimelineColor, ReportTimelineEntry } from './types'
import { DEMO_COMMIT_SHA, DEMO_PR_NUMBER, v2ReportLogic } from './v2ReportLogic'

const NOT_IN_DEMO = 'Not part of this demo'
const REVISE_TOAST = 'Not part of this demo. This would open a sidebar with the full task view of the completed PR.'

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

/** The side panel defaults to 512px; the demo chat opens at a quarter of the viewport instead, clamped to the panel's compact minimum. */
function openChatPanelWidth(): number {
    return Math.max(330, Math.round(window.innerWidth * 0.25))
}

/** Impact tiles come in twos, threes, and fours, so the column count is picked per report. */
const IMPACT_GRID: Record<number, string> = {
    1: 'grid-cols-1',
    2: 'grid-cols-2',
    3: 'grid-cols-3',
    4: 'grid-cols-4',
}

function slug(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9]+/g, '-')
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

function EvidenceCard({ card }: { card: ReportEvidenceCard }): JSX.Element {
    return (
        <Link
            to="#claims"
            disableClientSideRouting
            className="flex flex-col gap-2 rounded border border-primary bg-surface-secondary p-3 text-primary hover:border-accent hover:text-primary hover:no-underline"
            data-attr={`v2-report-evidence-${slug(card.label)}`}
        >
            <div className="flex items-center gap-2.5">
                <span className="flex-1 text-sm font-semibold">{card.title}</span>
                <span className="font-mono text-[11px] text-secondary">{card.label}</span>
            </div>
            {card.bars ? (
                <DemoBarStrip
                    values={card.bars.values}
                    alarmFromIndex={card.bars.alarmFromIndex}
                    height={34}
                    barWidth={8}
                    gap={5.4}
                />
            ) : null}
            <div className="text-[11px] leading-normal text-secondary">{card.detail}</div>
        </Link>
    )
}

function TimelineRow({ row }: { row: ReportTimelineEntry }): JSX.Element {
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

function MetricTile({ tile }: { tile: ReportImpactTile }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 rounded border border-primary bg-surface-secondary p-3.5">
            <span className="font-mono text-xl font-semibold">{tile.value}</span>
            <span className="text-[11px] leading-normal tracking-wide text-secondary">{tile.label}</span>
            {tile.note ? <span className="font-mono text-[11px] text-tertiary">{tile.note}</span> : null}
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

function GenerationChecklist({ step, steps }: { step: number; steps: string[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 rounded border border-primary bg-surface-secondary p-4">
            <div className="flex items-center gap-2">
                <PulsingDot />
                <span className="font-mono text-[10px] tracking-wider text-accent uppercase">
                    Generating the code change
                </span>
            </div>
            {steps.map((label, index) => {
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

export interface V2ReportSceneProps {
    id?: string
}

export function V2ReportScene({ id = DEMO_REPORT_ID }: V2ReportSceneProps = {}): JSX.Element {
    const {
        report,
        content,
        phase,
        generationStep,
        generationSteps,
        agentName,
        prModalOpen,
        codeOpen,
        evidenceExpanded,
        timeline,
        observationChart,
        observationValue,
        changeStats,
        monitoringCriteria,
    } = useValues(v2ReportLogic({ id }))
    const { startGeneration, sendToAgent, launch, setPrModalOpen, toggleCode, toggleEvidence } = useActions(
        v2ReportLogic({ id })
    )
    const { model, effort, rolloutStart, monitoringDays } = useValues(createPrModalLogic)
    const { sidePanelOpen, selectedTab, selectedTabOptions } = useValues(sidePanelStateLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const chatPanelOption = `${V2_REPORT_PANEL_OPTION}:${id}`
    const chatOpen = sidePanelOpen && selectedTab === SidePanelTab.Max && selectedTabOptions === chatPanelOption

    if (!report || !content) {
        return (
            <div className="mx-auto flex w-full max-w-md flex-col items-center gap-3 p-16 text-center">
                <p className="m-0 text-sm text-secondary">This report is not part of the demo.</p>
                <Link to={urls.v2Inbox()} data-attr="v2-report-missing-back">
                    Back to the inbox
                </Link>
            </div>
        )
    }

    const fix = content.fix
    const showChanges = !!fix && ['proposed', 'committed', 'launched'].includes(phase)
    const changesTitle =
        phase === 'proposed' ? 'Generated changes' : phase === 'committed' ? 'Changes from the commit' : 'Changes made'
    const committedByAgent = !!agentName && (phase === 'committed' || phase === 'launched')
    const filesLabel = `${changeStats.files} ${changeStats.files === 1 ? 'file' : 'files'}`
    const visibleEvidence = evidenceExpanded ? content.evidence : content.evidence.slice(0, 3)
    const hiddenEvidence = content.evidence.length - 3

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-2">
                <InboxBackButton className="-ml-[var(--button-padding-x-base)]" />
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconSparkles />}
                    onClick={() => {
                        if (chatOpen) {
                            closeSidePanel(SidePanelTab.Max)
                            return
                        }
                        resizerLogic
                            .findMounted({ logicKey: 'side-panel' })
                            ?.actions.setDesiredSize(openChatPanelWidth())
                        openSidePanel(SidePanelTab.Max, chatPanelOption)
                    }}
                    active={chatOpen}
                    data-attr="v2-report-ask-ai"
                >
                    Ask PostHog AI
                </LemonButton>
            </div>
            <div className="mx-auto flex w-full max-w-[1360px] flex-col gap-4">
                {report.status === 'Resolved' ? (
                    <LemonBanner
                        type="success"
                        action={{
                            children: 'See the resolution →',
                            to: urls.v2Resolved(id),
                            'data-attr': 'v2-report-open-resolved',
                        }}
                    >
                        <span className="text-sm font-normal">
                            This report resolved itself after the fix held for 7 days.
                        </span>
                    </LemonBanner>
                ) : fix && phase === 'launched' ? (
                    <LemonBanner
                        type="info"
                        action={{
                            children: 'Open fix monitor →',
                            to: urls.v2Monitor(id),
                            'data-attr': 'v2-report-open-monitor',
                        }}
                    >
                        <span className="text-sm font-normal">The fix is live and being monitored.</span>
                    </LemonBanner>
                ) : null}

                <div className="flex rounded-lg border border-primary bg-surface-primary max-lg:flex-col">
                    <aside className="flex w-[400px] flex-none flex-col gap-5 border-r border-primary p-5 max-lg:w-auto max-lg:border-r-0 max-lg:border-b">
                        <div className="flex flex-col gap-1">
                            <Microlabel>Observation</Microlabel>
                            <div className="text-xs leading-normal text-secondary">{content.observation.label}</div>
                            <div className="flex flex-wrap items-baseline gap-2.5">
                                <span className="font-mono text-2xl font-semibold">{observationValue}</span>
                                <span className="font-mono text-xs text-secondary">{content.observation.unit}</span>
                            </div>
                        </div>

                        <AnnotatedLineChart data={observationChart} height={130} live />

                        {content.occurrences ? (
                            <div className="flex flex-col gap-1.5">
                                <div className="text-[11px] leading-normal text-secondary">
                                    {content.occurrences.label}
                                </div>
                                <DemoBarStrip
                                    values={content.occurrences.values}
                                    alarmFromIndex={content.occurrences.alarmFromIndex}
                                />
                            </div>
                        ) : null}

                        <LemonDivider className="my-0" />

                        <div className="flex flex-col gap-2.5">
                            <Microlabel>Evidence</Microlabel>
                            {content.screenshot ? <EvidenceScreenshot screenshot={content.screenshot} /> : null}
                            {visibleEvidence.map((card) => (
                                <EvidenceCard key={card.title} card={card} />
                            ))}
                            {hiddenEvidence > 0 ? (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={toggleEvidence}
                                    className="self-start"
                                    data-attr="v2-report-toggle-evidence"
                                >
                                    {evidenceExpanded ? 'Show less' : `Show ${hiddenEvidence} more`}
                                </LemonButton>
                            ) : null}
                        </div>

                        <LemonDivider className="my-0" />

                        <div className="flex flex-col">
                            <Microlabel>Timeline</Microlabel>
                            <div className="mt-2 flex flex-col">
                                {timeline.map((row) => (
                                    <TimelineRow key={`${row.time}-${row.label}`} row={row} />
                                ))}
                            </div>
                        </div>
                    </aside>

                    <main className="min-w-0 flex-1 px-8 py-5">
                        <div className="mb-4 flex flex-wrap items-center gap-2.5 border-b border-primary pb-3">
                            <span className="text-sm font-semibold">Report summary</span>
                            <span className="font-mono text-[11px] text-secondary">
                                {report.id} · {report.area}
                            </span>
                            <span className="flex-1" />
                            <span className="text-xs text-tertiary">✦ Generated {report.created}</span>
                        </div>

                        <div className="flex flex-col gap-11">
                            <section className="flex flex-col gap-3.5">
                                <h1 className="m-0 text-2xl leading-tight font-bold">{content.verdictHeadline}</h1>
                                <p className="m-0 text-base leading-relaxed text-secondary">{report.verdict}</p>
                            </section>

                            <section className="flex flex-col gap-3">
                                <h2 className="m-0 text-lg font-semibold">Problem</h2>
                                {content.problem.map((paragraph) => (
                                    <p key={paragraph} className="m-0 text-[15px] leading-relaxed text-secondary">
                                        {paragraph}
                                    </p>
                                ))}
                                {content.replayCaption ? (
                                    <figure
                                        id="replay"
                                        className="m-0 mt-1 overflow-hidden rounded border border-primary bg-surface-secondary"
                                    >
                                        <div className="flex items-center gap-2.5 border-b border-primary px-3.5 py-2 font-mono text-[11px] text-secondary">
                                            <span className="h-1.5 w-1.5 flex-none rounded-full bg-success" />
                                            <span>session replay</span>
                                            <span className="flex-1" />
                                            <Link
                                                onClick={() => lemonToast.info(NOT_IN_DEMO)}
                                                className="text-[11px]"
                                                data-attr="v2-report-open-replay"
                                            >
                                                Open replay ↗
                                            </Link>
                                        </div>
                                        <figcaption className="px-4 py-3.5 text-sm leading-relaxed text-secondary">
                                            {content.replayCaption}
                                        </figcaption>
                                    </figure>
                                ) : null}
                            </section>

                            <section className="flex flex-col gap-3.5">
                                <h2 className="m-0 text-lg font-semibold">Impact</h2>
                                <div
                                    className={`grid gap-2.5 max-lg:grid-cols-1 ${
                                        IMPACT_GRID[content.impactTiles.length] ?? 'grid-cols-3'
                                    }`}
                                >
                                    {content.impactTiles.map((tile) => (
                                        <MetricTile key={tile.label} tile={tile} />
                                    ))}
                                </div>
                            </section>

                            <section id="claims" className="flex flex-col gap-4">
                                <h2 className="m-0 text-lg font-semibold">How we know</h2>
                                <div className="flex flex-col gap-2.5">
                                    {content.howWeKnow.map((claim, index) => (
                                        <NumberedClaim key={claim} index={index + 1}>
                                            {claim}
                                        </NumberedClaim>
                                    ))}
                                </div>
                                {content.causeDiff ? (
                                    <>
                                        {codeOpen ? (
                                            <DemoDiffBlock
                                                title={content.causeDiff.title}
                                                lines={diffLinesFromSnippet(content.causeDiff.snippet)}
                                            />
                                        ) : null}
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={toggleCode}
                                            className="self-start"
                                            data-attr="v2-report-toggle-code"
                                        >
                                            {codeOpen ? 'Hide the diff' : 'Show the code that caused it'}
                                        </LemonButton>
                                    </>
                                ) : null}
                            </section>

                            {fix ? (
                                <section id="fix" className="flex flex-col gap-3">
                                    <h2 className="m-0 text-lg font-semibold">Fix</h2>
                                    <p className="m-0 text-[15px] leading-relaxed text-secondary">{fix.summary}</p>

                                    {phase === 'reported' ? (
                                        <div className="flex flex-wrap items-center gap-2">
                                            <LemonButton
                                                type="primary"
                                                onClick={() => setPrModalOpen(true)}
                                                data-attr="v2-report-fix-and-monitor"
                                            >
                                                Fix &amp; monitor
                                            </LemonButton>
                                            <SendToAgentMenu promptText={fix.agentPrompt} onSelectAgent={sendToAgent}>
                                                <LemonButton
                                                    type="secondary"
                                                    sideIcon={<IconChevronDown />}
                                                    data-attr="v2-report-send-to-agent"
                                                >
                                                    Send to my agent
                                                </LemonButton>
                                            </SendToAgentMenu>
                                        </div>
                                    ) : null}

                                    {phase === 'generating' ? (
                                        <GenerationChecklist step={generationStep} steps={generationSteps} />
                                    ) : null}

                                    {phase === 'sent' ? (
                                        <div className="flex flex-col gap-2.5 rounded border border-primary bg-surface-secondary p-4">
                                            <div className="flex items-center gap-2">
                                                <PulsingDot />
                                                <span className="font-mono text-[10px] tracking-wider text-accent uppercase">
                                                    Handed off to {agentName}
                                                </span>
                                            </div>
                                            <div className="text-[13px] leading-relaxed text-secondary">
                                                Branch <Mono>{fix.branch}</Mono> created with the full report attached:
                                                root cause, evidence links, success criteria. This report is watching
                                                GitHub and will pick up the commit when it lands.
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
                                                    Commit detected on {fix.branch}
                                                </span>
                                            </div>
                                            <div className="text-[13px] leading-relaxed text-secondary">
                                                <Mono>{DEMO_COMMIT_SHA}</Mono> pushed via {agentName} 12 minutes ago,{' '}
                                                {filesLabel}, +{changeStats.added} −{changeStats.removed}. The diff
                                                matches the recommended fix and is shown below. Nothing has shipped yet:
                                                launching still runs it behind the flag with monitoring.
                                            </div>
                                            <div className="flex flex-wrap items-center gap-3">
                                                <LemonButton
                                                    type="primary"
                                                    onClick={launch}
                                                    data-attr="v2-report-launch-from-commit"
                                                >
                                                    Launch experiment &amp; monitor
                                                </LemonButton>
                                                <Link
                                                    onClick={() => lemonToast.info(NOT_IN_DEMO)}
                                                    className="text-[13px]"
                                                    data-attr="v2-report-view-commit"
                                                >
                                                    View commit on GitHub ↗
                                                </Link>
                                            </div>
                                        </div>
                                    ) : null}

                                    {phase === 'launched' ? (
                                        <p className="m-0 text-[13px] leading-relaxed text-success">
                                            ✓ Launched behind <Mono>{fix.flagKey}</Mono>. Live results are in the
                                            monitoring section below, day 1 of {monitoringDays}.
                                        </p>
                                    ) : null}
                                </section>
                            ) : report.live ? (
                                <section className="flex flex-col gap-2.5 rounded border border-primary bg-surface-secondary p-4">
                                    <div className="flex items-center gap-2">
                                        <PulsingDot />
                                        <span className="font-mono text-[10px] tracking-wider text-accent uppercase">
                                            Investigation still running
                                        </span>
                                    </div>
                                    <p className="m-0 text-[13px] leading-relaxed text-secondary">
                                        A fix proposal lands here when the storyboard completes. Chapters above are
                                        already final and will not change.
                                    </p>
                                    <LemonSkeleton className="h-1 max-w-[420px]" />
                                </section>
                            ) : report.status === 'Disputed' ? (
                                <LemonBanner type="warning">
                                    <span className="text-sm font-normal">{report.verdict}</span>
                                </LemonBanner>
                            ) : report.status === 'Dismissed' ? (
                                <section className="flex flex-col gap-2 rounded border border-primary bg-surface-secondary p-4">
                                    <span className="font-mono text-[10px] tracking-wider text-secondary uppercase">
                                        Dismissed
                                    </span>
                                    <p className="m-0 text-[13px] leading-relaxed text-secondary">{report.verdict}</p>
                                </section>
                            ) : null}

                            {showChanges && fix ? (
                                <section id="changes" className="flex flex-col gap-4">
                                    <div className="flex flex-col gap-2">
                                        <div className="flex flex-wrap items-center gap-2.5">
                                            <h2 className="m-0 text-lg font-semibold">{changesTitle}</h2>
                                            {phase !== 'committed' ? (
                                                <Link
                                                    onClick={() => lemonToast.info(NOT_IN_DEMO)}
                                                    className="font-mono text-[11px] font-semibold"
                                                    data-attr="v2-report-view-pr"
                                                >
                                                    {phase === 'proposed'
                                                        ? `draft PR #${DEMO_PR_NUMBER} on GitHub ↗`
                                                        : `PR #${DEMO_PR_NUMBER} ↗`}
                                                </Link>
                                            ) : null}
                                        </div>
                                        <div className="flex flex-wrap items-center gap-2.5 font-mono text-[11px] text-secondary">
                                            {committedByAgent ? (
                                                <span>
                                                    {fix.branch} · {DEMO_COMMIT_SHA} ·
                                                </span>
                                            ) : null}
                                            <span>
                                                <span className="font-semibold text-success">+{changeStats.added}</span>{' '}
                                                <span className="font-semibold text-danger">
                                                    −{changeStats.removed}
                                                </span>{' '}
                                                · {filesLabel}
                                            </span>
                                            <span className="rounded-full border border-primary bg-surface-secondary px-2 py-0.5 text-[10.5px]">
                                                {agentName ? `via ${agentName}` : `✦ ${model} · ${effort} effort`}
                                            </span>
                                        </div>
                                    </div>

                                    <div className="flex flex-col gap-2.5">
                                        {fix.changes.map((change, index) => (
                                            <div key={change.file} className="flex flex-col gap-2.5">
                                                <NumberedClaim index={index + 1}>
                                                    <strong className="font-mono text-[13px] text-primary">
                                                        {change.file}
                                                    </strong>
                                                </NumberedClaim>
                                                <DemoDiffBlock
                                                    className="ml-7"
                                                    lines={diffLinesFromSnippet(change.snippet)}
                                                />
                                                {change.note ? (
                                                    <p className="m-0 ml-7 text-[13px] leading-relaxed text-secondary">
                                                        {change.note}
                                                    </p>
                                                ) : null}
                                            </div>
                                        ))}
                                    </div>

                                    {phase === 'proposed' ? (
                                        <div className="flex flex-wrap items-center gap-2 border-t border-primary pt-4">
                                            <LemonButton
                                                type="primary"
                                                onClick={launch}
                                                data-attr="v2-report-approve-and-launch"
                                            >
                                                Approve &amp; launch experiment
                                            </LemonButton>
                                            <LemonButton
                                                type="secondary"
                                                onClick={() => lemonToast.info(REVISE_TOAST)}
                                                data-attr="v2-report-revise"
                                            >
                                                ✦ Ask PostHog AI to revise…
                                            </LemonButton>
                                            <SendToAgentMenu
                                                promptText={fix.agentPrompt}
                                                onSelectAgent={sendToAgent}
                                                placement="top-end"
                                            >
                                                <LemonButton
                                                    type="secondary"
                                                    sideIcon={<IconChevronDown />}
                                                    data-attr="v2-report-send-diff-to-agent"
                                                >
                                                    Send to my agent
                                                </LemonButton>
                                            </SendToAgentMenu>
                                        </div>
                                    ) : null}
                                </section>
                            ) : null}

                            {fix && phase === 'launched' ? (
                                <section id="monitor-inline" className="flex flex-col gap-3.5">
                                    <div className="flex flex-wrap items-center gap-2.5">
                                        <h2 className="m-0 text-lg font-semibold">Monitoring</h2>
                                        <LemonTag type="primary">Day 1 of {monitoringDays} · auto-halt armed</LemonTag>
                                        <span className="flex-1" />
                                        <Link
                                            to={urls.v2Monitor(id)}
                                            className="text-[13px] font-semibold"
                                            data-attr="v2-report-open-full-monitor"
                                        >
                                            Open full monitor →
                                        </Link>
                                    </div>
                                    <div className="flex flex-col gap-2 rounded border border-primary bg-surface-secondary p-4">
                                        <div className="flex items-baseline gap-2.5">
                                            <span className="font-mono text-xs text-secondary">{fix.flagKey}</span>
                                            <span className="flex-1" />
                                            <span className="font-mono text-lg font-semibold">{rolloutStart}%</span>
                                        </div>
                                        <LemonProgress percent={rolloutStart} strokeColor="var(--color-accent)" />
                                        <div className="flex justify-between font-mono text-[11px] text-secondary">
                                            <span className="font-semibold text-accent">{rolloutStart}% · now</span>
                                            <span>50% · day 2</span>
                                            <span>100% · day 3</span>
                                        </div>
                                    </div>
                                    <div className="flex flex-col">
                                        {monitoringCriteria.map((criterion) => (
                                            <CriteriaRow
                                                key={criterion}
                                                icon="●"
                                                iconClassName="bg-fill-info-highlight text-accent"
                                                label={criterion}
                                                value="watching"
                                                valueClassName="text-accent"
                                            />
                                        ))}
                                    </div>
                                </section>
                            ) : null}
                        </div>
                    </main>
                </div>

                {fix ? (
                    <CreatePrModal
                        isOpen={prModalOpen}
                        flagKey={fix.flagKey}
                        monitoringCriteria={fix.monitoringCriteria}
                        onClose={() => setPrModalOpen(false)}
                        onConfirm={startGeneration}
                    />
                ) : null}
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: V2ReportScene,
    logic: v2ReportLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id ?? DEMO_REPORT_ID }),
}

export default V2ReportScene
