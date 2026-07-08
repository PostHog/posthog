import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconClock, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { ExplorerHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { urls } from 'scenes/urls'

import { Card } from '../dashboard/Card'
import { formatMs, formatNumber } from '../dashboard/formatters'
import { HarnessLogo } from '../dashboard/harness'
import { METRICS_UNLOCK_LIFETIME_CALLS, mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'
import type { ChecklistItem, EarlyRecentCall } from './mcpEarlyDataLogic'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'

// Raw `$mcp_client_name` values don't match the backend-resolved harness labels the
// logo registry is keyed by; this maps the common spellings so rows get a logo.
// Unknown clients fall back to HarnessLogo's neutral dot.
const CLIENT_LABEL_RULES: Array<[RegExp, string]> = [
    [/claude[ ._-]?code/i, 'Claude Code'],
    [/claude[ ._-]?desktop/i, 'Claude Desktop'],
    [/claude[ ._-]?ai/i, 'Claude.ai'],
    [/claude/i, 'Claude.ai'],
    [/chatgpt/i, 'ChatGPT'],
    [/codex/i, 'OpenAI Codex'],
    [/openai/i, 'OpenAI'],
    [/cursor/i, 'Cursor'],
    [/windsurf/i, 'Windsurf'],
]

function guessHarnessLabel(clientName: string): string {
    return CLIENT_LABEL_RULES.find(([pattern]) => pattern.test(clientName))?.[1] ?? clientName
}

/**
 * The Activity tab: answers "what are agents doing with my server?" — a
 * plain-language summary instead of KPI tiles, the live feed as the hero, an
 * AI digest of agent intents, and an instrumentation checklist. It refreshes
 * live and is the default landing tab for low-volume projects, where the
 * windowed metrics dashboard would be noise; higher-volume projects land on
 * the Dashboard tab but can always come here for recency.
 */
export function MCPAnalyticsActivityDashboard(): JSX.Element {
    return (
        <div className="flex flex-col gap-4" data-attr="mcp-analytics-activity">
            <SummaryCard />
            <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
                <div className="lg:col-span-3">
                    <LiveActivityCard />
                </div>
                <div className="flex flex-col gap-4">
                    <IntentsCard />
                    <ClientsCard />
                    <ChecklistCard />
                </div>
            </div>
        </div>
    )
}

function SummaryCard(): JSX.Element {
    const { signals, dashboardStage } = useValues(mcpAnalyticsOnboardingLogic)
    const { summary, isRefreshing } = useValues(mcpEarlyDataLogic)
    const { refreshAll } = useActions(mcpEarlyDataLogic)

    return (
        // Same accent gradient as the first-look hero, so the product's intro
        // surfaces share a visual identity across stages.
        <Card className="bg-gradient-to-br from-accent/15 via-accent/5 to-surface-primary">
            <div className="flex items-center justify-between gap-4 flex-wrap">
                <div className="flex items-center gap-4 min-w-0">
                    <ExplorerHog className="h-20 w-20 shrink-0 hidden sm:block" />
                    <div className="min-w-0">
                        <h3 className="text-xl font-semibold m-0">
                            {summary}
                            {/* Omitted on day one — "since today" is noise. */}
                            {signals?.firstCallAt && !dayjs(signals.firstCallAt).isSame(dayjs(), 'day') ? (
                                <span className="text-muted font-normal">
                                    {' '}
                                    since {dayjs(signals.firstCallAt).format('MMM D')}
                                </span>
                            ) : null}
                        </h3>
                        <p className="text-muted text-base m-0 mt-1">
                            This view fills in live as agents use your server.
                            {dashboardStage === 'activity' ? (
                                <>
                                    {' '}
                                    Charts and trends live in the{' '}
                                    <Link to={urls.mcpAnalyticsDashboard()}>Dashboard tab</Link> — they get meaningful
                                    as usage grows (~{formatNumber(METRICS_UNLOCK_LIFETIME_CALLS)} calls).
                                </>
                            ) : null}
                        </p>
                    </div>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    loading={isRefreshing}
                    onClick={refreshAll}
                    data-attr="mcp-analytics-activity-refresh"
                >
                    Refresh
                </LemonButton>
            </div>
        </Card>
    )
}

function LiveActivityCard(): JSX.Element {
    const { recentCalls, overviewLoading } = useValues(mcpEarlyDataLogic)

    return (
        <Card title="Live activity" className="h-full" flush>
            {/* Roughly the top 10 rows visible; the rest scroll. */}
            <div className="max-h-[36rem] overflow-y-auto">
                <LemonTable<EarlyRecentCall>
                    embedded
                    dataSource={recentCalls}
                    loading={overviewLoading && recentCalls.length === 0}
                    rowKey={(row, index) => `${row.timestamp}-${row.tool}-${index}`}
                    emptyState="Waiting for the next tool call…"
                    columns={[
                        {
                            title: 'When',
                            key: 'timestamp',
                            width: 130,
                            render: (_, row) => <TZLabel time={row.timestamp} />,
                        },
                        {
                            title: 'Tool',
                            key: 'tool',
                            render: (_, row) => (
                                <span className="flex items-center gap-1 font-mono text-sm">
                                    {row.tool}
                                    {row.isError ? <LemonTag type="danger">error</LemonTag> : null}
                                </span>
                            ),
                        },
                        {
                            title: 'Agent intent',
                            key: 'intent',
                            render: (_, row) => (
                                <div>
                                    {row.intent ? (
                                        <span className="text-base">{row.intent}</span>
                                    ) : (
                                        <span className="text-muted text-base">—</span>
                                    )}
                                    {row.errorMessage ? (
                                        <div
                                            className="text-danger text-sm mt-0.5 line-clamp-2"
                                            title={row.errorMessage}
                                        >
                                            {row.errorMessage}
                                        </div>
                                    ) : null}
                                </div>
                            ),
                        },
                        {
                            title: 'Duration',
                            key: 'duration',
                            width: 90,
                            align: 'right',
                            render: (_, row) => (row.durationMs == null ? '—' : formatMs(row.durationMs)),
                        },
                        {
                            title: 'Client',
                            key: 'client',
                            width: 150,
                            render: (_, row) =>
                                row.clientName ? (
                                    <span className="flex items-center gap-1.5">
                                        <HarnessLogo
                                            category={guessHarnessLabel(row.clientName)}
                                            className="h-3.5 w-3.5"
                                        />
                                        <span className="truncate">{row.clientName}</span>
                                    </span>
                                ) : (
                                    <span className="text-muted">unknown</span>
                                ),
                        },
                    ]}
                />
            </div>
        </Card>
    )
}

// The AI digest is the product here: real intents are all worded differently, so
// verbatim grouping can't answer "what are agents trying to do". The raw list is
// strictly the degraded state for when generation is unavailable (no LLM key).
function IntentsCard(): JSX.Element {
    const { intentDigest, intentDigestLoading, intentThemes } = useValues(mcpEarlyDataLogic)

    return (
        <Card title="What agents are trying to do">
            {intentDigest?.digest ? (
                <div className="flex flex-col gap-2">
                    <p className="text-base m-0">{intentDigest.digest}</p>
                    <span className="text-muted text-sm">
                        AI summary of the last {formatNumber(intentDigest.intentCount)} agent intents
                    </span>
                </div>
            ) : intentDigestLoading ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-4 w-full" />
                    <LemonSkeleton className="h-4 w-5/6" />
                    <LemonSkeleton className="h-4 w-2/3" />
                    <span className="text-muted text-sm">Summarizing recent agent intents…</span>
                </div>
            ) : intentThemes.length === 0 ? (
                <span className="text-muted text-base">
                    No agent intents captured yet — they show up here as agents explain what they're doing.
                </span>
            ) : (
                <div className="flex flex-col gap-2">
                    <ul className="flex flex-col gap-2 m-0 pl-4">
                        {intentThemes.map(({ intent, count }) => (
                            <li key={intent} className="text-base">
                                {intent}
                                {count > 1 ? <span className="text-muted text-sm"> ×{count}</span> : null}
                            </li>
                        ))}
                    </ul>
                    <span className="text-muted text-sm">
                        AI summary unavailable — showing the most recent intents verbatim.
                    </span>
                </div>
            )}
        </Card>
    )
}

function ClientsCard(): JSX.Element {
    const { clients } = useValues(mcpEarlyDataLogic)
    const maxCalls = clients[0]?.calls ?? 0

    return (
        <Card title="Clients calling your server">
            {clients.length === 0 ? (
                <span className="text-muted text-base">No client info captured yet</span>
            ) : (
                <div className="flex flex-col gap-2">
                    {clients.map((row) => (
                        <div key={row.client}>
                            <div className="flex justify-between text-base">
                                <span className="flex items-center gap-1.5">
                                    <HarnessLogo category={guessHarnessLabel(row.client)} className="h-3.5 w-3.5" />
                                    {row.client}
                                </span>
                                <span className="text-muted">{formatNumber(row.calls)}</span>
                            </div>
                            <LemonProgress percent={maxCalls > 0 ? (row.calls / maxCalls) * 100 : 0} />
                        </div>
                    ))}
                </div>
            )}
        </Card>
    )
}

const CHECKLIST_ICONS: Record<ChecklistItem['status'], JSX.Element> = {
    ok: <IconCheckCircle className="text-success shrink-0 mt-0.5" />,
    warning: <IconWarning className="text-warning shrink-0 mt-0.5" />,
    pending: <IconClock className="text-muted shrink-0 mt-0.5" />,
}

function ChecklistCard(): JSX.Element {
    const { checklist } = useValues(mcpEarlyDataLogic)

    return (
        <Card title="Instrumentation checklist">
            <div className="flex flex-col gap-3">
                {checklist.map((item) => (
                    <div key={item.key} className="flex gap-2">
                        {CHECKLIST_ICONS[item.status]}
                        <div>
                            <div className="text-base font-medium">{item.title}</div>
                            <div className="text-muted text-sm">
                                {item.detail} {item.status !== 'ok' ? <Link to={item.docsUrl}>Learn more</Link> : null}
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </Card>
    )
}
