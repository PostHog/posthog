import './MCPToolCallPreview.scss'

import { sparkPaths } from 'lib/components/ProductEmptyState/previewSparkline'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

import { type BrandMarkName } from '../brandMarks'
import { BrandMark } from '../components/BrandMark'

type PreviewHarness = 'claude' | 'cursor' | 'openai'

interface PreviewCall {
    tool: string
    mark: BrandMarkName
    harness: PreviewHarness
    time: string
    error?: boolean
}

// Example tool calls - hand-authored, not real data. MCP tools are bare snake_case
// names (no parentheses - these are tool invocations, not function calls).
// `harness` tags a row for the filter chips.
const CALLS: PreviewCall[] = [
    { tool: 'search_docs', mark: 'Claude', harness: 'claude', time: '142ms' },
    { tool: 'create_issue', mark: 'Cursor', harness: 'cursor', time: 'err', error: true },
    { tool: 'run_query', mark: 'OpenAI', harness: 'openai', time: '210ms' },
    { tool: 'list_feature_flags', mark: 'Claude', harness: 'claude', time: '53ms' },
    { tool: 'get_schema', mark: 'Cursor', harness: 'cursor', time: '190ms' },
]

const FILTERS: { id: string; label: string; mark?: BrandMarkName }[] = [
    { id: 'all', label: 'All' },
    { id: 'claude', label: 'Claude', mark: 'Claude' },
    { id: 'cursor', label: 'Cursor', mark: 'Cursor' },
    { id: 'openai', label: 'Codex', mark: 'OpenAI' },
]

// Clients shown under the sparkline (the PostHog Desktop link is rendered separately, first).
const CLIENT_MARKS: BrandMarkName[] = ['Claude', 'OpenAI', 'Cursor', 'Windsurf']

// A hand-authored series for the sparkline — abstract, just enough to read as a rising trend.
const SPARK = [4, 6, 5, 7, 6, 9, 8, 10, 9, 12, 11, 14]
const { line, area } = sparkPaths(SPARK)

/**
 * Example-data preview for the MCP analytics empty state. All interaction and motion
 * are pure CSS (hidden radios drive the filter) - no timers or state, per the
 * preview rules in the `building-product-empty-states` skill.
 */
export function MCPToolCallPreview({ mode }: { mode: ProductEmptyStateMode }): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className="flex flex-col gap-3">
            <div className="MCPPreview">
                {/* Filter state, before the chips/rows so `:checked ~` can style them. */}
                {FILTERS.map((filter) => (
                    <input
                        key={filter.id}
                        type="radio"
                        name="mcp-preview-filter"
                        id={`mcp-preview-${filter.id}`}
                        defaultChecked={filter.id === 'all'}
                        className="MCPPreview__radio"
                    />
                ))}

                <div className="MCPPreview__head">
                    <span className="MCPPreview__title">Tool calls</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="MCPPreview__chips">
                    {FILTERS.map((filter) => (
                        <label
                            key={filter.id}
                            htmlFor={`mcp-preview-${filter.id}`}
                            className={`MCPPreview__chip MCPPreview__chip--${filter.id}`}
                        >
                            {filter.mark ? <BrandMark name={filter.mark} className="size-3" /> : null}
                            {filter.label}
                        </label>
                    ))}
                </div>

                {mode === 'waiting-for-data' ? (
                    <div className="MCPPreview__listening">
                        <Spinner className="text-sm" />
                        Listening for your first tool call…
                    </div>
                ) : null}

                <div className="MCPPreview__rows">
                    {CALLS.map((call, i) => (
                        <div
                            key={i}
                            className={cn('MCPPreview__row', call.error && 'MCPPreview__row--error')}
                            data-h={call.harness}
                        >
                            <span className="MCPPreview__logo">
                                <BrandMark name={call.mark} className="size-3.5" />
                            </span>
                            <span className="MCPPreview__tool">{call.tool}</span>
                            <span className="MCPPreview__time">{call.time}</span>
                        </div>
                    ))}
                </div>
            </div>

            <div className={cn('MCPSpark', isStatic && 'MCPSpark--static')}>
                <div className="MCPSpark__head">
                    <span className="MCPSpark__title">Tool calls · 7 days</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="MCPSpark__value">
                    1,284
                    <span className="MCPSpark__delta">▲ 18%</span>
                </div>

                <div className="MCPSpark__chart">
                    <svg className="MCPSpark__svg" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
                        <path className="MCPSpark__area" d={area} />
                        <path className="MCPSpark__line" d={line} vectorEffect="non-scaling-stroke" />
                        <path className="MCPSpark__trace" d={line} pathLength={100} vectorEffect="non-scaling-stroke" />
                    </svg>
                </div>

                <div className="MCPSpark__clients">
                    <Link
                        className="MCPSpark__code"
                        to="https://posthog.com/desktop?utm_medium=in-product&utm_campaign=mcp-analytics-empty-state"
                        target="_blank"
                        title="PostHog Desktop"
                    >
                        <BrandMark name="PostHog" label="PostHog Desktop" />
                    </Link>
                    {CLIENT_MARKS.map((mark) => (
                        <BrandMark key={mark} name={mark} />
                    ))}
                    <span className="MCPSpark__more">+12 clients</span>
                </div>
            </div>
        </div>
    )
}
