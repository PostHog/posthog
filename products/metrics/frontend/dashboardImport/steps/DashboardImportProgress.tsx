import clsx from 'clsx'
import { useValues } from 'kea'

import { IconCheck, IconCheckCircle, IconCircleDashed, IconMinus } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import type {
    DashboardImportPhaseEnumApi,
    PanelProgressStateEnumApi,
} from 'products/metrics/frontend/generated/api.schemas'

import { metricsDashboardImportLogic } from '../metricsDashboardImportLogic'

const PHASES: { key: DashboardImportPhaseEnumApi; label: string }[] = [
    { key: 'starting', label: 'Start agent' },
    { key: 'matching', label: 'Match panels' },
    { key: 'building', label: 'Build dashboard' },
    { key: 'checking_layout', label: 'Check layout' },
]

const PANEL_ICONS: Record<PanelProgressStateEnumApi, JSX.Element> = {
    done: <IconCheck className="text-success" />,
    working: <Spinner className="text-base" />,
    waiting: <IconCircleDashed className="text-muted" />,
    skipped: <IconMinus className="text-muted" />,
}

export function DashboardImportProgress(): JSX.Element {
    const { currentImport } = useValues(metricsDashboardImportLogic)
    const phase = currentImport?.phase ?? 'starting'
    const layoutRounds = currentImport?.layout_rounds ?? null
    const layoutRound = currentImport?.layout_round ?? 1
    const phases = layoutRounds ? PHASES : PHASES.filter((item) => item.key !== 'checking_layout')
    const phaseIndex = phases.findIndex((item) => item.key === phase)
    // Only the matching step has an agent at work. Before and after it, an unfinished panel just waits.
    const panels = (currentImport?.panel_progress ?? []).map((panel) =>
        phase !== 'matching' && panel.state === 'working' ? { ...panel, state: 'waiting' as const } : panel
    )
    const settled = panels.filter((panel) => panel.state === 'done' || panel.state === 'skipped').length
    // A screenshot import learns its panels while the agent works, so its total is not known yet.
    const knowsTotal = currentImport?.source === 'grafana' && panels.length > 0

    return (
        <div className="flex flex-col gap-4">
            <ol className="flex items-center gap-2 m-0 p-0 list-none">
                {phases.map((item, index) => (
                    <li key={item.key} className="flex items-center gap-2 flex-1 last:flex-none">
                        <span
                            className={clsx(
                                'flex items-center gap-1.5 text-sm whitespace-nowrap',
                                index > phaseIndex ? 'text-muted' : index === phaseIndex && 'font-semibold'
                            )}
                        >
                            {index < phaseIndex ? (
                                <IconCheckCircle className="text-success text-base" />
                            ) : index === phaseIndex ? (
                                <Spinner className="text-base" />
                            ) : (
                                <IconCircleDashed className="text-base" />
                            )}
                            {item.label}
                        </span>
                        {index < phases.length - 1 && <span className="h-px flex-1 bg-border" />}
                    </li>
                ))}
            </ol>
            {phase === 'checking_layout' && layoutRounds ? (
                <div className="flex flex-col gap-1.5">
                    <div className="flex justify-between text-xs text-secondary">
                        <span>Comparing the dashboard with your screenshot</span>
                        <span translate="no">{`Check ${layoutRound} of ${layoutRounds}`}</span>
                    </div>
                    <div className="flex h-2 gap-1">
                        {Array.from({ length: layoutRounds }, (_, index) => index + 1).map((check) => (
                            <span
                                key={check}
                                className={clsx(
                                    'flex-1 rounded',
                                    check < layoutRound
                                        ? 'bg-success'
                                        : check === layoutRound
                                          ? 'bg-success opacity-40 animate-pulse'
                                          : 'bg-muted-alt opacity-40'
                                )}
                            />
                        ))}
                    </div>
                </div>
            ) : knowsTotal ? (
                <div className="flex flex-col gap-1.5">
                    <div className="flex justify-between text-xs text-secondary">
                        <span>Panels ready</span>
                        <span translate="no">{`${settled} of ${panels.length}`}</span>
                    </div>
                    <LemonProgress percent={(100 * settled) / panels.length} strokeColor="var(--success)" />
                </div>
            ) : panels.length > 0 ? (
                <div className="text-xs text-secondary" translate="no">
                    {`${settled} panels matched`}
                </div>
            ) : phase === 'matching' ? (
                <div className="flex items-center gap-2 text-sm text-secondary">
                    <Spinner className="text-base" />
                    Reading the dashboard
                </div>
            ) : null}
            {panels.length > 0 && (
                <ul className="m-0 p-0 list-none max-h-80 overflow-y-auto rounded border divide-y">
                    {panels.map((panel) => (
                        <li key={panel.key} className="flex items-center gap-2 px-3 py-1.5 text-sm">
                            <span className="flex shrink-0 text-base">{PANEL_ICONS[panel.state]}</span>
                            <span className={clsx('truncate', panel.state === 'skipped' && 'text-muted')}>
                                {panel.title}
                            </span>
                            {panel.state === 'skipped' ? (
                                <span className="ml-auto shrink-0 text-xs text-muted">No equivalent</span>
                            ) : panel.state === 'working' ? (
                                <span className="ml-auto shrink-0 text-xs text-secondary">Checking</span>
                            ) : null}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}
