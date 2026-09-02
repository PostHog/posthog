import { Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { SignalReport } from '../../types'
import { deriveHeadline, parsePrUrlParts } from '../../utils/reportPresentation'
import { hasKnownSourceProduct, knownSourceProductEntries, SourceProductIconRow } from '../badges/sourceProductIcons'
import { resolveRunVariant, RunStatusIndicator, type RunVariant } from './runStatusVariant'

const RUN_VARIANT_TIMESTAMP_LABEL: Record<RunVariant, string> = {
    queued: 'Queued',
    live: 'Started',
    completed: 'Finished',
    failed: 'Failed',
}

function pickTimestamp(report: SignalReport, variant: RunVariant): string {
    if (variant === 'live') {
        return report.created_at
    }
    return report.updated_at ?? report.created_at
}

function RunSourceStack({ sourceProducts }: { sourceProducts?: string[] | null }): JSX.Element | null {
    const [primary, ...overflow] = knownSourceProductEntries(sourceProducts)
    if (!primary) {
        return null
    }
    return (
        <span className="inline-flex items-center gap-2 min-w-0">
            <SourceProductIconRow
                entries={[primary, ...overflow]}
                className="inline-flex items-center gap-1.5 shrink-0"
            />
            <span>
                {primary.meta.label}
                {overflow.length > 0 ? ` + ${overflow.length}` : null}
            </span>
        </span>
    )
}

function prRef(prUrl: string | null | undefined): string | null {
    const parts = prUrl ? parsePrUrlParts(prUrl) : null
    return parts ? `#${parts.number}` : null
}

export function AgentRunCard({ report }: { report: SignalReport }): JSX.Element {
    const hasSource = hasKnownSourceProduct(report.source_products)
    const pr = prRef(report.implementation_pr_url)
    const variant = resolveRunVariant(report.status)
    const timestampSource = pickTimestamp(report, variant)
    const headline = deriveHeadline(report.summary)

    return (
        <Link
            to={urls.inboxReport('reports', report.id)}
            className="group flex w-full items-start gap-3 rounded border border-primary bg-surface-primary px-4 py-3.5 text-left text-inherit no-underline transition-colors duration-150 hover:border-primary hover:bg-surface-secondary"
        >
            <RunStatusIndicator variant={variant} className="mt-0.5" />

            <div className="flex flex-col gap-1.5 min-w-0 flex-1">
                <span className="break-words min-w-0 font-semibold text-sm leading-snug tracking-tight">
                    {report.title ?? 'Untitled run'}
                </span>
                {headline ? (
                    <p className="break-words line-clamp-2 text-xs text-secondary leading-snug m-0">{headline}</p>
                ) : null}
                <div className="flex items-center gap-2 flex-wrap mt-1.5 text-xs text-tertiary leading-none select-none">
                    {hasSource ? (
                        <>
                            <RunSourceStack sourceProducts={report.source_products} />
                            <span aria-hidden>·</span>
                        </>
                    ) : null}
                    <span className="inline-flex items-center gap-1">
                        {RUN_VARIANT_TIMESTAMP_LABEL[variant]} <TZLabel time={timestampSource} />
                    </span>
                </div>
            </div>

            {pr ? (
                <span className="self-center shrink-0 border-l border-primary pl-3 font-mono tabular-nums text-xs text-tertiary">
                    {pr}
                </span>
            ) : null}
        </Link>
    )
}
