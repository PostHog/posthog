import './MCPToolCallPreview.scss'

import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

import posthogCodeLogo from 'public/posthog-icon.svg'

import claudeLogo from '../harness-logos/claude.svg'
import cursorLogo from '../harness-logos/cursor.svg'
import openaiLogo from '../harness-logos/openai.svg'
import windsurfLogo from '../harness-logos/windsurf.svg'

type PreviewHarness = 'claude' | 'cursor' | 'openai'

interface PreviewCall {
    tool: string
    logo: string
    harness: PreviewHarness
    time: string
    error?: boolean
}

// Example tool calls - hand-authored, not real data. MCP tools are bare snake_case
// names (no parentheses - these are tool invocations, not function calls).
// `harness` tags a row for the filter chips.
const CALLS: PreviewCall[] = [
    { tool: 'search_docs', logo: claudeLogo, harness: 'claude', time: '142ms' },
    { tool: 'create_issue', logo: cursorLogo, harness: 'cursor', time: 'err', error: true },
    { tool: 'run_query', logo: openaiLogo, harness: 'openai', time: '210ms' },
    { tool: 'list_feature_flags', logo: claudeLogo, harness: 'claude', time: '53ms' },
    { tool: 'get_schema', logo: cursorLogo, harness: 'cursor', time: '190ms' },
]

const FILTERS: { id: string; label: string; logo?: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'claude', label: 'Claude', logo: claudeLogo },
    { id: 'cursor', label: 'Cursor', logo: cursorLogo },
    { id: 'openai', label: 'Codex', logo: openaiLogo },
]

// Clients shown under the sparkline (the PostHog Code link is rendered separately, first).
const CLIENT_LOGOS = [claudeLogo, openaiLogo, cursorLogo, windsurfLogo]

// A hand-authored series for the sparkline — abstract, just enough to read as a rising trend.
const SPARK = [4, 6, 5, 7, 6, 9, 8, 10, 9, 12, 11, 14]

function sparkPaths(): { line: string; area: string } {
    const width = 100
    const height = 40
    const pad = 3
    const min = Math.min(...SPARK)
    const max = Math.max(...SPARK)
    const points = SPARK.map((value, i) => {
        const x = (i / (SPARK.length - 1)) * width
        const y = height - pad - ((value - min) / (max - min || 1)) * (height - 2 * pad)
        return `${x.toFixed(1)} ${y.toFixed(1)}`
    })
    const line = 'M ' + points.join(' L ')
    return { line, area: `${line} L ${width} ${height} L 0 ${height} Z` }
}

/**
 * Example-data preview for the MCP analytics empty state. All interaction and motion
 * are pure CSS (hidden radios drive the filter) - no timers or state, per the
 * preview rules in the `building-product-empty-states` skill.
 */
export function MCPToolCallPreview({ mode }: { mode: ProductEmptyStateMode }): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()
    const { line, area } = sparkPaths()

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
                            {filter.logo ? <img src={filter.logo} alt="" /> : null}
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
                                <img src={call.logo} alt="" />
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
                        to="https://posthog.com/code?utm_medium=in-product&utm_campaign=mcp-analytics-empty-state"
                        target="_blank"
                        title="PostHog Code"
                    >
                        <img src={posthogCodeLogo} alt="PostHog Code" />
                    </Link>
                    {CLIENT_LOGOS.map((logo, i) => (
                        <img key={i} src={logo} alt="" />
                    ))}
                    <span className="MCPSpark__more">+12 clients</span>
                </div>
            </div>
        </div>
    )
}
