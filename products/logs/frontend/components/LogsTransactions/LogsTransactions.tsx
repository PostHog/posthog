/**
 * Placeholder results region for the Transactions view mode (behind the `logs-transactions` flag).
 * Swapped in by LogsViewer the same way LogsPatterns is; the actual transactions UI lands here.
 */
export function LogsTransactions(): JSX.Element {
    return (
        <div className="flex-1 min-h-0 flex items-center justify-center" data-attr="logs-transactions">
            <span className="text-muted text-sm">Transactions view coming soon</span>
        </div>
    )
}
