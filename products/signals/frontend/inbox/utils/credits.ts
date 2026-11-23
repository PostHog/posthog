// Keep the conversion aligned with SIGNALS_CREDITS_PER_DOLLAR in backend/pricing.py.
const CREDITS_PER_DOLLAR = 100

const creditNumber = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

export function usdToCredits(usd: number): number {
    return usd * CREDITS_PER_DOLLAR
}

export function formatCredits(credits: number): string {
    const amount = creditNumber.format(credits)
    return `${amount} ${amount === '1' ? 'credit' : 'credits'}`
}
