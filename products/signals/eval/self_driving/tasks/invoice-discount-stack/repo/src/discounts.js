import { DISCOUNTS } from '../data/discounts.js'

export function savingsFor(discount, subtotalCents) {
  if (discount.kind === 'percent') {
    return Math.round((subtotalCents * discount.percent) / 100)
  }
  return Math.min(discount.amountCents, subtotalCents)
}

export function eligibleDiscounts(codes, subtotalCents, now = new Date()) {
  const wanted = new Set(codes.map((code) => String(code).trim().toUpperCase()))
  return DISCOUNTS.filter(
    (discount) =>
      wanted.has(discount.code) &&
      new Date(discount.expiresAt) > now &&
      subtotalCents >= (discount.minSubtotalCents ?? 0)
  )
}

// Candidates are sorted best-first, so the first entry is the discount we apply.
export function pickBestDiscount(codes, subtotalCents, now = new Date()) {
  const candidates = eligibleDiscounts(codes, subtotalCents, now).map((discount) => ({
    discount,
    savings: savingsFor(discount, subtotalCents),
  }))
  if (candidates.length === 0) {
    return null
  }
  candidates.sort((a, b) => a.savings - b.savings)
  return candidates[0]
}
