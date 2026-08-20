import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconTrending } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { CreatePrModal } from './components/CreatePrModal'
import { DemoDiffBlock, diffLinesFromSnippet } from './components/DemoDiffBlock'
import { SendToAgentMenu } from './components/SendToAgentMenu'
import { DemoReport, FocusActedStatus, ReportStatus, ReportTrend } from './types'
import { v2FocusLogic } from './v2FocusLogic'

export const scene: SceneExport = {
    component: V2FocusScene,
    logic: v2FocusLogic,
}

const STATUS_TAG_TYPE: Record<ReportStatus | FocusActedStatus, LemonTagType> = {
    New: 'primary',
    Investigating: 'highlight',
    Assigned: 'option',
    Viewed: 'muted',
    Verifying: 'highlight',
    Resolved: 'success',
    Disputed: 'warning',
    Dismissed: 'muted',
    Acknowledged: 'success',
    'In progress': 'highlight',
}

/** Dot color for a report already acted on, so the progress row reads as an outcome trail. */
const ACTED_DOT_CLASS: Record<FocusActedStatus, string> = {
    Acknowledged: 'bg-success',
    'In progress': 'bg-accent',
    Dismissed: 'bg-border-secondary',
}

const TREND_CLASS: Record<ReportTrend, string> = {
    up: 'text-danger',
    down: 'text-success',
    flat: 'text-tertiary',
}

const SHORTCUT_HELP: { id: string; keys: JSX.Element; description: string }[] = [
    {
        id: 'next',
        keys: (
            <>
                <KeyboardShortcut j />
                <KeyboardShortcut arrowdown />
            </>
        ),
        description: 'Next report',
    },
    {
        id: 'previous',
        keys: (
            <>
                <KeyboardShortcut k />
                <KeyboardShortcut arrowup />
            </>
        ),
        description: 'Previous report',
    },
    {
        id: 'expand',
        keys: (
            <>
                <KeyboardShortcut enter />
                <KeyboardShortcut e />
            </>
        ),
        description: 'Show the full report',
    },
    { id: 'collapse', keys: <KeyboardShortcut escape />, description: 'Collapse the report, or leave focus mode' },
    { id: 'acknowledge', keys: <KeyboardShortcut a />, description: 'Acknowledge and advance' },
    { id: 'primary-action', keys: <KeyboardShortcut i />, description: 'Run the primary action' },
    { id: 'dismiss', keys: <KeyboardShortcut d />, description: 'Dismiss and advance' },
    { id: 'send-to-agent', keys: <KeyboardShortcut s />, description: 'Send to agent' },
]

function TrendAnnotation({ trend, label }: { trend: ReportTrend; label: string }): JSX.Element {
    const Icon = trend === 'up' ? IconTrending : trend === 'down' ? IconTrendingDown : IconTrendingFlat
    return (
        <span className={cn('flex items-center gap-1 font-mono text-xs', TREND_CLASS[trend])}>
            <Icon />
            {label}
        </span>
    )
}

function PeekStrip({
    report,
    shortcut,
    onClick,
    dataAttr,
}: {
    report: DemoReport
    shortcut: JSX.Element
    onClick: () => void
    dataAttr: string
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            data-attr={dataAttr}
            className="flex w-full max-w-2xl flex-none items-center gap-3 overflow-hidden rounded border border-primary bg-surface-primary px-4 py-1.5 opacity-50 transition-opacity hover:opacity-100 motion-reduce:transition-none"
        >
            {shortcut}
            <span className="truncate text-xs text-secondary">{report.headline}</span>
        </button>
    )
}

function HintBarItem({ shortcut, label }: { shortcut: JSX.Element; label: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1.5">
            {shortcut}
            <span>{label}</span>
        </span>
    )
}

export function V2FocusScene(): JSX.Element {
    const {
        reports,
        currentIndex,
        currentReport,
        counter,
        expanded,
        actedStatuses,
        agentMenuOpen,
        helpOpen,
        prModalOpen,
    } = useValues(v2FocusLogic)
    const {
        navigate,
        jumpTo,
        toggleExpanded,
        setExpanded,
        acknowledge,
        dismiss,
        runPrimaryAction,
        confirmPr,
        sendToAgent,
        setAgentMenuOpen,
        setHelpOpen,
        setPrModalOpen,
    } = useActions(v2FocusLogic)

    const modalOpen = prModalOpen || helpOpen
    // While the agent menu is open it owns the keyboard, so only escape stays live.
    const triageDisabled = modalOpen || agentMenuOpen

    useKeyboardHotkeys(
        {
            j: { action: () => navigate(1), disabled: triageDisabled },
            arrowdown: { action: () => navigate(1), disabled: triageDisabled },
            k: { action: () => navigate(-1), disabled: triageDisabled },
            arrowup: { action: () => navigate(-1), disabled: triageDisabled },
            enter: {
                // Enter on a focused button has to activate that button, not toggle the card
                action: (event) => {
                    if ((event.target as HTMLElement | null)?.closest('a, button')) {
                        return
                    }
                    event.preventDefault()
                    toggleExpanded()
                },
                disabled: triageDisabled,
                willHandleEvent: true,
            },
            e: { action: () => toggleExpanded(), disabled: triageDisabled },
            a: { action: () => acknowledge(), disabled: triageDisabled },
            i: { action: () => runPrimaryAction(), disabled: triageDisabled },
            d: { action: () => dismiss(), disabled: triageDisabled },
            s: { action: () => setAgentMenuOpen(true), disabled: triageDisabled },
            escape: {
                // Escape peels back one layer: the agent menu, then the expanded report, then focus mode itself
                action: () => {
                    if (agentMenuOpen) {
                        setAgentMenuOpen(false)
                    } else if (expanded) {
                        setExpanded(false)
                    } else {
                        router.actions.push(urls.v2Inbox())
                    }
                },
                disabled: modalOpen,
            },
        },
        [triageDisabled, modalOpen, agentMenuOpen, expanded]
    )

    const report = currentReport
    const focus = report?.focus
    const previousReport = currentIndex > 0 ? reports[currentIndex - 1] : null
    const nextReport = currentIndex < reports.length - 1 ? reports[currentIndex + 1] : null

    return (
        <div className="flex h-full flex-col overflow-hidden">
            <header className="flex flex-none items-center gap-3 border-b border-primary px-4 py-2">
                <Link to={urls.v2Inbox()} className="text-xs text-secondary" data-attr="v2-focus-back">
                    ← Inbox
                </Link>
                <span className="font-mono text-xxs tracking-widest text-tertiary uppercase">Focus</span>
                <div className="flex-1" />
                <div className="flex items-center gap-1.5">
                    {reports.map((report, index) => {
                        const acted = actedStatuses[report.id]
                        const isCurrent = index === currentIndex
                        return (
                            <button
                                key={report.id}
                                type="button"
                                onClick={() => jumpTo(index)}
                                aria-label={`Go to report ${index + 1}, ${report.headline}`}
                                aria-current={isCurrent ? 'true' : undefined}
                                data-attr="v2-focus-progress-dot"
                                className={cn(
                                    'rounded-full',
                                    isCurrent
                                        ? 'size-2.5 bg-accent'
                                        : cn('size-2', acted ? ACTED_DOT_CLASS[acted] : 'bg-border-primary')
                                )}
                            />
                        )
                    })}
                </div>
                <span className="font-mono text-xs text-secondary">{counter}</span>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={() => setHelpOpen(true)}
                    aria-label="Keyboard shortcuts"
                    data-attr="v2-focus-help"
                >
                    ?
                </LemonButton>
            </header>

            <main className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 py-4">
                {previousReport ? (
                    <PeekStrip
                        report={previousReport}
                        shortcut={<KeyboardShortcut k />}
                        onClick={() => navigate(-1)}
                        dataAttr="v2-focus-peek-previous"
                    />
                ) : null}

                {report && focus ? (
                    <article
                        key={report.id}
                        className="flex max-h-full w-full max-w-3xl min-h-0 flex-col overflow-hidden rounded-lg border border-primary bg-surface-primary shadow-sm transition-[opacity,transform] duration-200 starting:translate-y-2 starting:opacity-0 motion-reduce:transition-none"
                    >
                        <div className="flex flex-none flex-wrap items-center gap-3 px-6 pt-4">
                            <span className="font-mono text-xxs tracking-widest text-tertiary">{report.area}</span>
                            <div className="flex-1" />
                            <LemonTag
                                type={STATUS_TAG_TYPE[actedStatuses[report.id] ?? report.status]}
                                size="small"
                                className="font-mono uppercase"
                            >
                                {actedStatuses[report.id] ?? report.status}
                            </LemonTag>
                        </div>

                        <h1
                            className={cn(
                                'm-0 flex-none px-6 pt-2 font-bold leading-tight',
                                expanded ? 'text-base' : 'text-2xl'
                            )}
                        >
                            {report.headline}
                        </h1>

                        {!expanded ? (
                            <>
                                <div className="flex flex-none flex-wrap items-baseline gap-3 px-6 pt-4">
                                    <span className="font-mono text-2xl font-semibold">{report.impact}</span>
                                    <TrendAnnotation trend={report.trend} label={focus.trendLabel} />
                                    <div className="flex-1" />
                                    <span className="text-xs text-tertiary">{focus.age}</span>
                                </div>
                                <p className="m-0 flex-none px-6 pt-3 text-sm leading-relaxed">{report.verdict}</p>
                                <div className="flex-none px-6 pt-2 pb-4 font-mono text-xs text-secondary">
                                    {report.proof}
                                </div>
                            </>
                        ) : (
                            <div className="mt-3 flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto border-t border-primary p-6">
                                {focus.story.map((section) => (
                                    <div key={section.label} className="flex flex-col gap-2">
                                        <div className="font-mono text-xxs font-semibold tracking-widest text-tertiary uppercase">
                                            {section.label}
                                        </div>
                                        <div className="text-sm leading-relaxed">{section.body}</div>
                                        {section.code ? (
                                            <DemoDiffBlock lines={diffLinesFromSnippet(section.code)} />
                                        ) : null}
                                    </div>
                                ))}
                                {report.content ? (
                                    <Link
                                        to={urls.v2Report(report.id)}
                                        className="text-xs"
                                        data-attr="v2-focus-full-report"
                                    >
                                        Full report →
                                    </Link>
                                ) : null}
                            </div>
                        )}

                        <div className="flex flex-none items-center gap-2 border-t border-primary px-4 py-2">
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={acknowledge}
                                sideIcon={<KeyboardShortcut a />}
                                data-attr="v2-focus-acknowledge"
                            >
                                Acknowledge
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={runPrimaryAction}
                                sideIcon={<KeyboardShortcut i />}
                                data-attr="v2-focus-primary-action"
                            >
                                {focus.actionLabel}
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={dismiss}
                                sideIcon={<KeyboardShortcut d />}
                                data-attr="v2-focus-dismiss"
                            >
                                Dismiss
                            </LemonButton>
                            <SendToAgentMenu
                                visible={agentMenuOpen}
                                onVisibilityChange={setAgentMenuOpen}
                                placement="top-end"
                                promptText={`Fix ${report.id}: ${report.headline}. Pull the full report with the PostHog MCP: posthog issue ${report.id}.`}
                                onSelectAgent={sendToAgent}
                            >
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    sideIcon={<KeyboardShortcut s />}
                                    data-attr="v2-focus-send-to-agent"
                                >
                                    Send to agent
                                </LemonButton>
                            </SendToAgentMenu>
                            <div className="flex-1" />
                            <LemonButton
                                type="tertiary"
                                size="small"
                                onClick={toggleExpanded}
                                sideIcon={<KeyboardShortcut enter />}
                                data-attr="v2-focus-toggle-report"
                            >
                                {expanded ? 'Collapse' : 'Show report'}
                            </LemonButton>
                        </div>
                    </article>
                ) : (
                    <div className="text-sm text-secondary">Nothing left to triage.</div>
                )}

                {nextReport ? (
                    <PeekStrip
                        report={nextReport}
                        shortcut={<KeyboardShortcut j />}
                        onClick={() => navigate(1)}
                        dataAttr="v2-focus-peek-next"
                    />
                ) : null}
            </main>

            <footer className="flex flex-none flex-wrap items-center justify-center gap-x-4 gap-y-1 border-t border-primary px-4 py-1.5 text-xxs text-tertiary">
                <HintBarItem shortcut={<KeyboardShortcut arrowdown />} label="next" />
                <HintBarItem shortcut={<KeyboardShortcut arrowup />} label="previous" />
                <HintBarItem shortcut={<KeyboardShortcut enter />} label="show report" />
                <HintBarItem shortcut={<KeyboardShortcut a />} label="acknowledge" />
                <HintBarItem shortcut={<KeyboardShortcut i />} label="fix & monitor" />
                <HintBarItem shortcut={<KeyboardShortcut d />} label="dismiss" />
                <HintBarItem shortcut={<KeyboardShortcut s />} label="send to agent" />
                <HintBarItem shortcut={<KeyboardShortcut escape />} label="back" />
            </footer>

            <CreatePrModal
                isOpen={prModalOpen}
                flagKey={focus?.flagKey ?? ''}
                onClose={() => setPrModalOpen(false)}
                onConfirm={confirmPr}
            />

            <LemonModal
                isOpen={helpOpen}
                onClose={() => setHelpOpen(false)}
                title="Keyboard shortcuts"
                width={360}
                data-attr="v2-focus-shortcuts"
            >
                <div className="flex flex-col gap-2">
                    {SHORTCUT_HELP.map((shortcut) => (
                        <div key={shortcut.id} className="flex items-center gap-3">
                            <span className="flex w-20 flex-none items-center gap-1">{shortcut.keys}</span>
                            <span className="text-sm">{shortcut.description}</span>
                        </div>
                    ))}
                </div>
            </LemonModal>
        </div>
    )
}

export default V2FocusScene
