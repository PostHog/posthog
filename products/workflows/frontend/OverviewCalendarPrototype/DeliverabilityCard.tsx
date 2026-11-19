import { IconCheck, IconWarning } from '@posthog/icons'
import { Button, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill'
// PROTOTYPE (throwaway): send health. Gauges against the limits that cut a daily send limit, the sending domain's
// records, today's use of the daily limit, and delivery by mailbox provider.
import { Gauge } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { ChartCard } from './ChartCard'
import { EmptyInsight } from './EmptyInsight'
import { DAILY_LIMIT, DOMAIN_CHECKS, MAILBOX_PROVIDERS } from './insightsData'
import { SENDING_DOMAIN, formatCount, percent } from './prototypeData'
import { prototypeToast } from './prototypeToast'

const GAUGES = [
    {
        label: 'Bounced',
        value: 1.8,
        max: 8,
        thresholds: [
            { value: 0, color: 'var(--data-color-7)', label: 'Healthy' },
            { value: 2, color: 'var(--data-color-13)', label: 'Watch' },
            { value: 5, color: 'var(--data-color-5)', label: 'Daily limit drops' },
        ],
        decimals: 1,
    },
    {
        label: 'Spam complaints',
        value: 0.04,
        max: 0.2,
        thresholds: [
            { value: 0, color: 'var(--data-color-7)', label: 'Healthy' },
            { value: 0.08, color: 'var(--data-color-13)', label: 'Watch' },
            { value: 0.1, color: 'var(--data-color-5)', label: 'Mailbox providers block' },
        ],
        decimals: 2,
    },
    {
        label: 'Unsubscribed',
        value: 0.21,
        max: 2,
        thresholds: [
            { value: 0, color: 'var(--data-color-7)', label: 'Healthy' },
            { value: 0.5, color: 'var(--data-color-13)', label: 'Watch' },
            { value: 1, color: 'var(--data-color-5)', label: 'High' },
        ],
        decimals: 2,
    },
]

export function DeliverabilityCard({ noDomain }: { noDomain: boolean }): JSX.Element {
    const theme = useChartTheme()
    if (noDomain) {
        return (
            <ChartCard title="Deliverability" description="Email">
                <EmptyInsight
                    title="Verify a sending domain"
                    detail="Add SPF, DKIM and DMARC records for your domain, so mailbox providers trust your email. Bounce, spam and delivery numbers show here once you send."
                >
                    <Button variant="primary" size="sm" onClick={() => prototypeToast('the sending domain setup')}>
                        Add a sending domain
                    </Button>
                </EmptyInsight>
            </ChartCard>
        )
    }
    const usedShare = DAILY_LIMIT.used / DAILY_LIMIT.limit
    return (
        <ChartCard
            title="Deliverability"
            description="Email, last 7 days"
            action={
                <Button variant="link" onClick={() => prototypeToast('the reputation page')}>
                    Reputation
                </Button>
            }
        >
            <div className="grid gap-6 @min-[64rem]:grid-cols-2">
                <div className="flex min-w-0 flex-col gap-4">
                    <div className="grid grid-cols-3 gap-2">
                        {GAUGES.map((g) => (
                            <div key={g.label} className="flex h-32 min-w-0 flex-col">
                                <Gauge
                                    value={g.value}
                                    min={0}
                                    max={g.max}
                                    thresholds={g.thresholds}
                                    theme={theme}
                                    label={g.label}
                                    config={{ valueFormatter: (v) => `${v.toFixed(g.decimals)}%` }}
                                />
                            </div>
                        ))}
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                        <div className="flex flex-col gap-1.5">
                            <span className="text-xs font-medium text-muted-foreground">{SENDING_DOMAIN}</span>
                            <div className="flex flex-wrap gap-3">
                                {DOMAIN_CHECKS.map((c) => (
                                    <span key={c.key} className="inline-flex items-center gap-1 text-sm">
                                        {c.ok ? (
                                            <IconCheck className="size-4 text-success-foreground" />
                                        ) : (
                                            <IconWarning className="size-4 text-destructive-foreground" />
                                        )}
                                        {c.label}
                                    </span>
                                ))}
                            </div>
                            <Button
                                variant="link"
                                size="inline"
                                className="self-start"
                                onClick={() => prototypeToast('the DKIM record to fix')}
                            >
                                Fix DKIM
                            </Button>
                        </div>
                        <div className="flex flex-col gap-1.5">
                            <span className="text-xs font-medium text-muted-foreground">Daily limit today</span>
                            <div className="h-2 overflow-hidden rounded-full bg-fill-hover">
                                <div
                                    className={
                                        usedShare > 0.8
                                            ? 'h-full bg-warning-foreground'
                                            : 'h-full bg-[var(--data-color-1)]'
                                    }
                                    style={{ width: `${usedShare * 100}%` }}
                                />
                            </div>
                            <span className="text-xs text-muted-foreground">
                                {formatCount(DAILY_LIMIT.used)} of {formatCount(DAILY_LIMIT.limit)} used
                            </span>
                            <Button
                                variant="link"
                                size="inline"
                                className="self-start"
                                onClick={() => prototypeToast('the request for a higher sending limit')}
                            >
                                Request a higher limit
                            </Button>
                        </div>
                    </div>
                </div>
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>Mailbox provider</TableHead>
                            <TableHead className="text-right">Share</TableHead>
                            <TableHead className="text-right">Delivered</TableHead>
                            <TableHead className="text-right">Opened</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {MAILBOX_PROVIDERS.map((m) => (
                            <TableRow key={m.key}>
                                <TableCell>
                                    <Button
                                        variant="link"
                                        size="inline"
                                        onClick={() => prototypeToast(`${m.label} on the reputation page`)}
                                    >
                                        {m.label}
                                    </Button>
                                </TableCell>
                                <TableCell className="text-right tabular-nums">{percent(m.share)}</TableCell>
                                <TableCell
                                    className={
                                        m.delivered < 0.97
                                            ? 'text-right tabular-nums text-warning-foreground'
                                            : 'text-right tabular-nums'
                                    }
                                >
                                    {percent(m.delivered)}
                                </TableCell>
                                <TableCell className="text-right tabular-nums">{percent(m.opened)}</TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
        </ChartCard>
    )
}
