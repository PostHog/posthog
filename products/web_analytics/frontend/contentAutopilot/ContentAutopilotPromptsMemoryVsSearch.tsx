import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import type { MemoryVsSearchRow } from './promptsOverview'

const RateFigure = ({ label, rate }: { label: string; rate: string | null }): JSX.Element => (
    <div className="flex flex-col min-w-0">
        <span className="text-muted text-xs">{label}</span>
        <span className="text-xl font-semibold tabular-nums">{rate ?? '-'}</span>
    </div>
)

/** Per engine, how often answers name the brand from training data alone against with web search. */
export const ContentAutopilotPromptsMemoryVsSearch = ({ rows }: { rows: MemoryVsSearchRow[] }): JSX.Element => (
    <PagePerformanceCard className="min-w-0">
        <PagePerformanceCardHeader title="Memory vs search" />
        {rows.length === 0 ? (
            <div className="p-3" data-attr="content-autopilot-prompts-overview-memory-empty">
                <h4 className="m-0">No answers without search yet</h4>
                <p className="m-0 mt-1 text-muted max-w-2xl">
                    When no-search checks are on, each prompt is also asked once a week with web search turned off. That
                    shows what each model says about you from its training data alone. Results appear here after the
                    first checks run. If this stays empty, no-search checks are off for this project.
                </p>
            </div>
        ) : (
            <div className="flex flex-col" data-attr="content-autopilot-prompts-overview-memory">
                <p className="m-0 px-3 pt-3 text-muted text-xs">
                    How often each model names you from its training data alone, compared with when it searches the web.
                    Both rates cover the same prompts.
                </p>
                <ul className="m-0 p-0 list-none divide-y">
                    {rows.map((row) => (
                        <li key={row.engine} className="flex flex-col gap-2 p-3">
                            <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
                                <span className="font-semibold w-20">{row.label}</span>
                                <RateFigure label="From memory" rate={row.memoryRate} />
                                <RateFigure label="With search" rate={row.searchRate} />
                                {row.gap ? (
                                    <Tooltip title={row.gap.tooltip}>
                                        <LemonTag type="muted" size="small" className="tabular-nums mb-1">
                                            {row.gap.direction === 'flat' ? 'No gap' : `${row.gap.label} with search`}
                                        </LemonTag>
                                    </Tooltip>
                                ) : null}
                            </div>
                            <p className="m-0">{row.summary}</p>
                            <span className="text-muted text-xs">{row.note}</span>
                        </li>
                    ))}
                </ul>
            </div>
        )}
    </PagePerformanceCard>
)
