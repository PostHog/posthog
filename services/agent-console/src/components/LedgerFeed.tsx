/**
 * Ledger feed — paginated list of ai-gateway ledger entries
 * (debits / topups / refunds / adjustments). Newest first, cursor-paged.
 *
 * Sourced from `listLedger` (see [src/lib/apiClient.ts:listLedger]).
 * Each entry shows transaction type, amount (signed), model, and a
 * monospace reference_id. The reference_id format
 * `agent:<session_id>:<turn>` doubles as a session id surface — we
 * link these to /agents/<slug>/sessions/<session_id> when a slug
 * mapping is available, but for v1 just render plain text.
 */

import { Button } from '@posthog/quill'

import type { AIGatewayLedgerEntry, AIGatewayLedgerListResponse, AIGatewayTransactionType } from '@/lib/apiClient'

const TYPE_LABELS: Record<AIGatewayTransactionType, string> = {
    debit: 'debit',
    topup: 'topup',
    refund: 'refund',
    adjustment: 'adjustment',
}

const TYPE_FILTERS: Array<{ key: AIGatewayTransactionType | 'all'; label: string }> = [
    { key: 'all', label: 'All' },
    { key: 'debit', label: 'Debits' },
    { key: 'topup', label: 'Top-ups' },
    { key: 'refund', label: 'Refunds' },
    { key: 'adjustment', label: 'Adjustments' },
]

export interface LedgerFeedProps {
    page: AIGatewayLedgerListResponse
    loading?: boolean
    error?: string
    filterType: AIGatewayTransactionType | 'all'
    onChangeFilter: (next: AIGatewayTransactionType | 'all') => void
    /** Loaded more rows get appended to `page.results` upstream — feed
     * just signals the click. */
    onLoadMore?: () => void
    loadingMore?: boolean
}

export function LedgerFeed({
    page,
    loading,
    error,
    filterType,
    onChangeFilter,
    onLoadMore,
    loadingMore,
}: LedgerFeedProps): React.ReactElement {
    return (
        <div className="overflow-hidden rounded-md border border-border bg-card">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
                <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Ledger</h3>
                <div className="flex gap-1">
                    {TYPE_FILTERS.map((f) => (
                        <FilterChip
                            key={f.key}
                            label={f.label}
                            active={filterType === f.key}
                            onClick={() => onChangeFilter(f.key)}
                        />
                    ))}
                </div>
            </div>

            {error ? (
                <div className="px-3 py-6 text-xs text-destructive-foreground">{error}</div>
            ) : loading && page.results.length === 0 ? (
                <div className="px-3 py-6 text-xs italic text-muted-foreground">Loading…</div>
            ) : page.results.length === 0 ? (
                <div className="px-3 py-6 text-xs italic text-muted-foreground">No entries.</div>
            ) : (
                <>
                    <ul className="divide-y divide-border/60">
                        {page.results.map((e) => (
                            <li key={e.id}>
                                <LedgerRow entry={e} />
                            </li>
                        ))}
                    </ul>
                    {page.next_cursor && onLoadMore ? (
                        <div className="flex justify-center border-t border-border px-3 py-2">
                            <Button size="sm" variant="outline" onClick={onLoadMore} disabled={loadingMore}>
                                {loadingMore ? 'Loading…' : 'Load more'}
                            </Button>
                        </div>
                    ) : null}
                </>
            )}
        </div>
    )
}

function LedgerRow({ entry }: { entry: AIGatewayLedgerEntry }): React.ReactElement {
    // debits move money out (negative from the team's view), topups move
    // money in. refund + adjustment can go either way; we use source/dest
    // to infer the sign relative to the prepaid bucket.
    const sign = signFor(entry)
    const amount = Number(entry.amount_usd)
    const formatted = `${sign < 0 ? '-' : sign > 0 ? '+' : ''}$${formatUsd(amount)}`
    const tone = sign < 0 ? 'text-destructive-foreground' : sign > 0 ? 'text-success-foreground' : 'text-foreground'

    return (
        <div className="flex items-center gap-3 px-3 py-2">
            <span className="w-20 shrink-0 text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
                {TYPE_LABELS[entry.transaction_type]}
            </span>
            <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 text-xs">
                    {entry.model ? (
                        <span className="truncate font-mono text-foreground">{entry.model}</span>
                    ) : (
                        <span className="text-muted-foreground">—</span>
                    )}
                    {entry.provider ? (
                        <span className="text-[0.6875rem] text-muted-foreground">{entry.provider}</span>
                    ) : null}
                </div>
                {entry.reference_id ? (
                    <div className="mt-0.5 truncate font-mono text-[0.6875rem] text-muted-foreground">
                        {entry.reference_id}
                    </div>
                ) : null}
            </div>
            <div className="flex shrink-0 flex-col items-end">
                <span className={`font-mono text-sm tabular-nums ${tone}`}>{formatted}</span>
                <span className="text-[0.625rem] text-muted-foreground">{formatRelative(entry.created_at)}</span>
            </div>
        </div>
    )
}

function FilterChip({
    label,
    active,
    onClick,
}: {
    label: string
    active: boolean
    onClick: () => void
}): React.ReactElement {
    const cls = active
        ? 'cursor-pointer rounded-full bg-foreground px-2 py-0.5 text-[0.625rem] font-medium text-background'
        : 'cursor-pointer rounded-full border border-border bg-card px-2 py-0.5 text-[0.625rem] text-muted-foreground transition-colors hover:text-foreground'
    return (
        <button type="button" onClick={onClick} className={cls} aria-pressed={active}>
            {label}
        </button>
    )
}

function signFor(e: AIGatewayLedgerEntry): -1 | 0 | 1 {
    // From the team's wallet perspective: anything flowing into prepaid
    // is +, anything flowing out is -.
    if (e.destination === 'prepaid') {
        return 1
    }
    if (e.source === 'prepaid') {
        return -1
    }
    return 0
}

function formatUsd(n: number): string {
    if (!Number.isFinite(n)) {
        return '0.00'
    }
    if (Math.abs(n) >= 1) {
        return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    }
    return n.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 })
}

function formatRelative(iso: string): string {
    const ts = new Date(iso).getTime()
    if (!ts) {
        return '—'
    }
    const diff = Math.max(0, Date.now() - ts)
    const minute = 60 * 1000
    const hour = 60 * minute
    const day = 24 * hour
    if (diff < minute) {
        return 'just now'
    }
    if (diff < hour) {
        return `${Math.floor(diff / minute)}m ago`
    }
    if (diff < day) {
        return `${Math.floor(diff / hour)}h ago`
    }
    return `${Math.floor(diff / day)}d ago`
}
