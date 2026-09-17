import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'
import { Badge, Card, CardContent, CardHeader, CardTitle } from '@posthog/quill-primitives'

import { dataColorVars } from 'lib/colors'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { formatNumber } from '../dashboard/formatters'
import type { MCPIntentThemeApi } from '../generated/api.schemas'
import { mcpOverviewLogic } from './mcpOverviewLogic'
import { formatPct } from './overviewCopy'
import { ToolTag } from './ToolTag'

/** At or above this, a theme is working. Below the warning bound, it is a problem worth naming. */
const THEME_SUCCESS_PCT = 95
const THEME_WARNING_PCT = 85

function successVariant(successPct: number): 'success' | 'warning' | 'destructive' {
    if (successPct >= THEME_SUCCESS_PCT) {
        return 'success'
    }
    return successPct >= THEME_WARNING_PCT ? 'warning' : 'destructive'
}

function IntentThemeRow({
    theme,
    total,
    color,
}: {
    theme: MCPIntentThemeApi
    total: number
    color: string
}): JSX.Element {
    const sharePct = total > 0 ? (theme.intent_count / total) * 100 : 0
    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-medium text-primary">{theme.name}</span>
                <span className="flex items-center gap-2">
                    <Badge variant={successVariant(theme.success_pct)}>{formatPct(theme.success_pct)} worked</Badge>
                    <span className="text-muted" translate="no">
                        {formatPct(sharePct)}
                    </span>
                </span>
            </div>
            <LemonProgress percent={sharePct} strokeColor={color} bgColor="var(--color-bg-surface-tertiary)" />
            <p className="m-0 text-sm italic text-muted">{theme.example_intent}</p>
            {theme.tools.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    {theme.tools.map((tool) => (
                        <ToolTag key={tool} name={tool} />
                    ))}
                </div>
            )}
        </div>
    )
}

/**
 * Agent intents grouped into themes by an LLM. Real intents are all worded differently, so
 * grouping verbatim text cannot answer "what are people trying to do"; without the LLM there
 * is no degraded version of this card worth showing.
 */
export function IntentThemesCard(): JSX.Element {
    const { intentDigest, intentDigestLoading } = useValues(mcpOverviewLogic)
    const hasThemes = !!intentDigest?.digest && intentDigest.themes.length > 0

    return (
        <Card size="sm" className="gap-0">
            <CardHeader className="flex-row items-center justify-between gap-2 border-b border-border pb-3">
                <CardTitle>What people are trying to do</CardTitle>
                {hasThemes && (
                    <span className="text-xs text-muted" translate="no">
                        Grouped from {formatNumber(intentDigest.intentCount)} agent intents
                    </span>
                )}
            </CardHeader>
            <CardContent className="flex flex-col gap-4 pt-3">
                {intentDigestLoading && !hasThemes ? (
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton className="h-4 w-full" />
                        <LemonSkeleton className="h-4 w-5/6" />
                        <LemonSkeleton className="h-4 w-2/3" />
                        <span className="text-sm text-muted">Summarizing recent agent intents...</span>
                    </div>
                ) : !hasThemes ? (
                    <span className="text-sm text-muted">
                        No themes yet. They show up here once agents record what they are trying to do, and the
                        summarizer is available.
                    </span>
                ) : (
                    <>
                        <p className="m-0 text-sm text-primary">{intentDigest.digest}</p>
                        {intentDigest.themes.map((theme, index) => (
                            <IntentThemeRow
                                key={`${index}-${theme.name}`}
                                theme={theme}
                                total={intentDigest.intentCount}
                                color={`var(--${dataColorVars[index % dataColorVars.length]})`}
                            />
                        ))}
                    </>
                )}
            </CardContent>
        </Card>
    )
}
