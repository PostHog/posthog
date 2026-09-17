import { useValues } from 'kea'

import { Badge, Card, CardContent, CardHeader, CardTitle } from '@posthog/quill-primitives'

import { Link } from 'lib/lemon-ui/Link/Link'

import { mcpOverviewLogic } from './mcpOverviewLogic'
import type { CoverageBadge } from './overviewCoverage'

const BADGE_VARIANT: Record<CoverageBadge, 'success' | 'warning' | 'info'> = {
    OK: 'success',
    Fix: 'warning',
    Info: 'info',
}

/** Where the numbers above come from, and where they stop being able to answer. */
export function CoverageCard(): JSX.Element {
    const { coverageItems } = useValues(mcpOverviewLogic)

    return (
        <Card size="sm" className="gap-0">
            <CardHeader className="flex-row items-center justify-between gap-2 border-b border-border pb-3">
                <CardTitle>Can you trust the numbers above?</CardTitle>
                <span className="text-xs text-muted">What the SDK is and is not capturing</span>
            </CardHeader>
            <CardContent className="pt-3">
                <div className="@container/mcp-coverage">
                    <div className="grid grid-cols-1 gap-4 @min-[36rem]/mcp-coverage:grid-cols-2 @min-[60rem]/mcp-coverage:grid-cols-3 @min-[80rem]/mcp-coverage:grid-cols-5">
                        {coverageItems.map((item) => (
                            <div key={item.key} className="flex gap-2">
                                <Badge variant={BADGE_VARIANT[item.badge]} className="mt-0.5 shrink-0">
                                    {item.badge}
                                </Badge>
                                <div className="flex min-w-0 flex-col">
                                    <span className="text-sm font-medium text-primary">{item.title}</span>
                                    <span className="text-sm text-muted">
                                        {item.detail}{' '}
                                        {item.link && (
                                            <Link
                                                to={item.link.to}
                                                target={item.link.to.startsWith('http') ? '_blank' : undefined}
                                            >
                                                {item.link.label}
                                            </Link>
                                        )}
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </CardContent>
        </Card>
    )
}
