/**
 * Wallet card — surfaces the team's ai-gateway prepaid balance, pending
 * holds, account profile, and kill-switch state. Sourced from
 * `getWallet` (see [src/lib/apiClient.ts:getWallet]).
 *
 * Tile tones:
 *   - destructive when kill_switch.tripped (red border)
 *   - attention when available_usd < 10% of spendable_usd (amber)
 *   - default otherwise
 */

import { AlertOctagonIcon, AlertTriangleIcon } from 'lucide-react'

import type { AIGatewayWallet } from '@/lib/apiClient'

export interface WalletCardProps {
    wallet: AIGatewayWallet
}

export function WalletCard({ wallet }: WalletCardProps): React.ReactElement {
    const available = Number(wallet.available_usd)
    const spendable = Number(wallet.spendable_usd)
    const lowBalance = spendable > 0 && available < spendable * 0.1
    const tripped = wallet.kill_switch.tripped

    const toneClass = tripped
        ? 'border-destructive bg-destructive/5'
        : lowBalance
          ? 'border-warning bg-warning/5'
          : 'border-border bg-card'

    return (
        <div className={`overflow-hidden rounded-md border ${toneClass}`}>
            <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Wallet</h3>
                {tripped ? (
                    <span className="inline-flex items-center gap-1 text-[0.6875rem] font-medium text-destructive-foreground">
                        <AlertOctagonIcon className="h-3 w-3" />
                        Kill switch tripped
                    </span>
                ) : lowBalance ? (
                    <span className="inline-flex items-center gap-1 text-[0.6875rem] font-medium text-warning-foreground">
                        <AlertTriangleIcon className="h-3 w-3" />
                        Low balance
                    </span>
                ) : null}
            </div>
            <div className="grid grid-cols-1 gap-3 px-3 py-3 sm:grid-cols-3">
                <BigNumber label="Available" value={`$${formatUsd(available)}`} />
                <BigNumber label="Pending" value={`$${formatUsd(Number(wallet.pending_usd))}`} />
                <BigNumber label="Spendable" value={`$${formatUsd(spendable)}`} hint="balance + allowance" />
            </div>
            <dl className="grid grid-cols-2 gap-y-1.5 border-t border-border px-3 py-3 text-xs">
                <Dt>Plan</Dt>
                <Dd>{profileLabel(wallet.account.profile)}</Dd>

                <Dt>Period</Dt>
                <Dd>{wallet.account.period}</Dd>

                {wallet.account.overage_allowance_usd !== '0' && wallet.account.overage_allowance_usd !== '0.000000' ? (
                    <>
                        <Dt>Overage allowance</Dt>
                        <Dd>${formatUsd(Number(wallet.account.overage_allowance_usd))}</Dd>
                    </>
                ) : null}

                {wallet.rolling_hour_usd ? (
                    <>
                        <Dt>Rolling hour</Dt>
                        <Dd>
                            ${formatUsd(Number(wallet.rolling_hour_usd))}
                            {wallet.kill_switch.threshold_usd
                                ? ` / $${formatUsd(Number(wallet.kill_switch.threshold_usd))} threshold`
                                : ''}
                        </Dd>
                    </>
                ) : null}

                {tripped && wallet.kill_switch.tripped_at ? (
                    <>
                        <Dt>Tripped</Dt>
                        <Dd className="text-destructive-foreground">
                            {new Date(wallet.kill_switch.tripped_at).toLocaleString()}
                        </Dd>
                    </>
                ) : null}
            </dl>
        </div>
    )
}

function BigNumber({ label, value, hint }: { label: string; value: string; hint?: string }): React.ReactElement {
    return (
        <div>
            <div className="text-[0.6875rem] uppercase tracking-wide text-muted-foreground">{label}</div>
            <div className="mt-0.5 font-mono text-xl tabular-nums text-foreground">{value}</div>
            {hint ? <div className="text-[0.6875rem] text-muted-foreground">{hint}</div> : null}
        </div>
    )
}

function Dt({ children }: { children: React.ReactNode }): React.ReactElement {
    return <dt className="text-muted-foreground">{children}</dt>
}

function Dd({ children, className = '' }: { children: React.ReactNode; className?: string }): React.ReactElement {
    return <dd className={`truncate text-right ${className}`.trim()}>{children}</dd>
}

function profileLabel(p: 'A' | 'B' | 'C'): string {
    switch (p) {
        case 'A':
            return 'Absorbed (internal)'
        case 'B':
            return 'Internal overage'
        case 'C':
            return 'Prepaid'
    }
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
