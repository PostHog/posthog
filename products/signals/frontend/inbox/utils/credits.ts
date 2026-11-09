// Keep the conversion aligned with SIGNALS_CREDITS_PER_DOLLAR in backend/pricing.py.
const CREDITS_PER_DOLLAR = 100

const creditNumber = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

export function usdToCredits(usd: number): number {
    return usd * CREDITS_PER_DOLLAR
}

export function formatCredits(credits: number): string {
    if (credits > 0 && credits < 0.01) {
        return '<0.01 credits'
    }
    const amount = creditNumber.format(credits)
    return `${amount} ${amount === '1' ? 'credit' : 'credits'}`
}
