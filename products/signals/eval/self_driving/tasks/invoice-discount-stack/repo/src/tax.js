const TAX_RATES = {
  US: 0,
  EU: 0.21,
  UK: 0.2,
}

export function taxFor(amountCents, region = 'US') {
  const rate = TAX_RATES[region] ?? 0
  return Math.round(amountCents * rate)
}
