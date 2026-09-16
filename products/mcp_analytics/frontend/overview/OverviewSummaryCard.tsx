import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSkeleton, Link } from '@posthog/lemon-ui'
import { Card, CardContent } from '@posthog/quill-primitives'

import { urls } from 'scenes/urls'

import { formatNumber } from '../dashboard/formatters'
import { mcpDateSearchParams } from '../mcpAnalyticsToolQualityLogic'
import { mcpOverviewLogic } from './mcpOverviewLogic'
import { formatPct } from './overviewCopy'

function SummaryMeta(): JSX.Element | null {
    const { summary, dateFilter } = useValues(mcpOverviewLogic)

    if (!summary) {
        return null
    }
    return (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
            <span translate="no">{formatNumber(summary.calls)} calls</span>
            <span translate="no">{formatNumber(summary.sessions)} sessions</span>
            <span translate="no">Intent on {formatPct(summary.intent_pct)} of calls</span>
            <Link to={combineUrl(urls.mcpAnalyticsDashboard(), mcpDateSearchParams(dateFilter)).url}>
                Charts and trends
            </Link>
        </div>
    )
}

function AskBar(): JSX.Element {
    const { askInput } = useValues(mcpOverviewLogic)
    const { setAskInput, askPostHogAI } = useActions(mcpOverviewLogic)

    return (
        <form
            className="flex max-w-[48rem] items-center gap-2"
            onSubmit={(event) => {
                event.preventDefault()
                if (askInput.trim()) {
                    askPostHogAI(askInput.trim(), 'input')
                }
            }}
        >
            <LemonInput
                value={askInput}
                onChange={setAskInput}
                placeholder="Ask anything about how people use your MCP..."
                prefix={<IconSparkles />}
                fullWidth
                data-attr="mcp-overview-ask-input"
            />
            <LemonButton
                type="primary"
                htmlType="submit"
                disabledReason={askInput.trim() ? undefined : 'Type a question first'}
                data-attr="mcp-overview-ask-submit"
            >
                Ask
            </LemonButton>
        </form>
    )
}

function SuggestionChips(): JSX.Element | null {
    const { suggestions } = useValues(mcpOverviewLogic)
    const { askPostHogAI } = useActions(mcpOverviewLogic)

    if (suggestions.length === 0) {
        return null
    }
    return (
        <div className="flex flex-wrap gap-2">
            {suggestions.map((suggestion) => (
                <LemonButton
                    key={suggestion.key}
                    type="secondary"
                    size="xsmall"
                    onClick={() => askPostHogAI(suggestion.prompt, suggestion.key)}
                    data-attr="mcp-overview-ask-suggestion"
                >
                    {suggestion.label}
                </LemonButton>
            ))}
        </div>
    )
}

/** The one thing a reader should take away from the window, plus a way to ask about it. */
export function OverviewSummaryCard(): JSX.Element {
    const { headline, summary, summaryLoading } = useValues(mcpOverviewLogic)

    return (
        <Card size="sm">
            <CardContent className="flex flex-col gap-3">
                {summaryLoading && !summary ? (
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton className="h-6 w-full" />
                        <LemonSkeleton className="h-6 w-4/5" />
                    </div>
                ) : (
                    <p className="m-0 max-w-[60rem] text-lg font-medium text-pretty text-primary">{headline}</p>
                )}
                <SummaryMeta />
                <AskBar />
                <SuggestionChips />
            </CardContent>
        </Card>
    )
}
