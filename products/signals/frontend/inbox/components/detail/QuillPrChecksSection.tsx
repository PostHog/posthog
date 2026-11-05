import { useValues } from 'kea'

import {
    IconCheckCircle,
    IconCircleDashed,
    IconClockRewind,
    IconExternal,
    IconSpinner,
    IconWarning,
    IconX,
} from '@posthog/icons'
import {
    Button,
    Card,
    CardGroup,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Skeleton,
    Text,
    cn,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { CHECK_VARIANT_LABELS, CHECK_VARIANT_ORDER, CheckVariant, summarizePrChecks } from './prChecksPresentation'
import { QuillDetailSection } from './QuillDetailSection'

const VARIANT_META: Record<CheckVariant, { icon: JSX.Element; className: string }> = {
    failure: { icon: <IconWarning />, className: 'text-destructive-foreground' },
    cancelled: { icon: <IconX />, className: 'text-muted-foreground' },
    pending: {
        icon: <IconSpinner className="animate-spin motion-reduce:animate-none" />,
        className: 'text-warning-foreground',
    },
    stale: { icon: <IconClockRewind />, className: 'text-muted-foreground' },
    success: { icon: <IconCheckCircle />, className: 'text-success-foreground' },
    neutral: { icon: <IconCircleDashed />, className: 'text-subtle-foreground' },
}

function CheckSummaryList({
    counts,
    compact,
}: {
    counts: Record<CheckVariant, number>
    compact: boolean
}): JSX.Element {
    return (
        <span
            className={cn('items-center gap-x-2.5 text-xxs', compact ? 'inline-flex' : 'flex w-full flex-wrap gap-y-1')}
        >
            {CHECK_VARIANT_ORDER.filter((variant) => counts[variant] > 0).map((variant) => {
                const variantLabel = CHECK_VARIANT_LABELS[variant].toLowerCase()
                return (
                    <span
                        key={variant}
                        className={cn(
                            'inline-flex items-center gap-1 whitespace-nowrap',
                            VARIANT_META[variant].className
                        )}
                        title={compact ? `${counts[variant]} ${variantLabel}` : undefined}
                    >
                        <span aria-hidden className="flex items-center [&_svg]:size-3">
                            {VARIANT_META[variant].icon}
                        </span>
                        <span className="font-medium tabular-nums">{counts[variant]}</span>
                        <span className={compact ? 'sr-only' : undefined}>{variantLabel}</span>
                    </span>
                )
            })}
        </span>
    )
}

/** The quill sibling of `PrChecksSection`, for the report page behind `today-rail-nav`. */
export function QuillPrChecksSection({ report }: { report: SignalReport }): JSX.Element | null {
    const { prChecks, prChecksLoading, prChecksError } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )

    // Never loaded yet: show a skeleton. Loaded-but-empty: nothing to show, so drop the section.
    if (prChecks === null) {
        if (!prChecksLoading && !prChecksError) {
            return null
        }
    } else if (prChecks.length === 0 && !prChecksError) {
        return null
    }

    const { sorted, counts } = summarizePrChecks(prChecks)

    return (
        <QuillDetailSection
            icon={<IconCheckCircle />}
            title="CI checks"
            collapsible
            // `QuillDetailSection` reads `defaultCollapsed` only on mount, so remount when an error appears
            // or clears. The header shows the per-status counts, so the list stays collapsed and does
            // not push the sections under it out of view. An error stays open so it is not hidden.
            key={prChecksError ? 'checks-error' : 'checks'}
            defaultCollapsed={!prChecksError}
            meta={
                sorted.length > 0 ? (open) => (open ? null : <CheckSummaryList counts={counts} compact />) : undefined
            }
            summary={
                sorted.length > 0
                    ? (open) => (open ? <CheckSummaryList counts={counts} compact={false} /> : null)
                    : undefined
            }
        >
            {prChecksError ? (
                <Item variant="outline" tone="destructive" size="sm" className="flex-wrap">
                    <ItemContent>
                        <ItemDescription>{prChecksError.message}</ItemDescription>
                    </ItemContent>
                    {prChecksError.remediationUrl ? (
                        <ItemActions>
                            <Button variant="outline" render={<LinkPrimitive to={prChecksError.remediationUrl} />}>
                                Open GitHub integration settings
                            </Button>
                        </ItemActions>
                    ) : null}
                </Item>
            ) : prChecks === null ? (
                <div className="flex flex-col gap-1">
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-full" />
                </div>
            ) : (
                <div className="max-h-96 overflow-y-auto scroll-mask-y-4 scroll-py-4">
                    <CardGroup size="sm">
                        {sorted.map(({ check, variant }, i) => {
                            const row = (
                                <>
                                    <span
                                        className={cn(
                                            'flex shrink-0 items-center [&_svg]:size-4',
                                            VARIANT_META[variant].className
                                        )}
                                        aria-hidden
                                    >
                                        {VARIANT_META[variant].icon}
                                    </span>
                                    <Text
                                        size="xs"
                                        weight="medium"
                                        render={<span />}
                                        className="min-w-0 flex-1 truncate"
                                        title={check.name}
                                    >
                                        {check.name}
                                    </Text>
                                    <Text size="xs" variant="muted" render={<span />} className="shrink-0">
                                        {CHECK_VARIANT_LABELS[variant]}
                                    </Text>
                                    {check.url && <IconExternal className="size-3.5 shrink-0 text-subtle-foreground" />}
                                </>
                            )
                            return (
                                <Card key={`${check.name}-${i}`} size="sm" className="p-0">
                                    {check.url ? (
                                        <LinkPrimitive
                                            to={check.url}
                                            target="_blank"
                                            className="flex w-full min-w-0 items-center gap-2.5 px-3 py-2.5 text-foreground no-underline hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30"
                                        >
                                            {row}
                                        </LinkPrimitive>
                                    ) : (
                                        <span className="flex min-w-0 items-center gap-2.5 px-3 py-2.5">{row}</span>
                                    )}
                                </Card>
                            )
                        })}
                    </CardGroup>
                </div>
            )}
        </QuillDetailSection>
    )
}
