const currency = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
})

/** Recorded spend arrives in cents. */
export function formatRecordedSpend(amount: number | null | undefined): string {
    return amount == null ? 'Not tracked' : currency.format(amount / 100)
}

export function recordedSpendTooltip(amount: number | null | undefined, description?: string): string {
    return [
        description,
        amount == null
            ? 'Usage was not recorded for this activity.'
            : 'Recorded usage in USD, before credits and billing exemptions.',
    ]
        .filter(Boolean)
        .join(' ')
}
