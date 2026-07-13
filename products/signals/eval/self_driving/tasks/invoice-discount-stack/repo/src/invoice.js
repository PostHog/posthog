import { capture } from './analytics.js'
import { pickBestDiscount } from './discounts.js'
import { formatCents } from './money.js'
import { taxFor } from './tax.js'

export function createInvoice(cart, discountCodes = [], options = {}) {
  const subtotalCents = cart.items.reduce((sum, item) => sum + item.priceCents * item.quantity, 0)
  const best = pickBestDiscount(discountCodes, subtotalCents, options.now)
  const discountCents = best ? best.savings : 0
  const taxedBaseCents = subtotalCents - discountCents
  const taxCents = taxFor(taxedBaseCents, cart.region)
  const totalCents = taxedBaseCents + taxCents

  const invoice = {
    customerId: cart.customerId,
    subtotalCents,
    discount: best ? { code: best.discount.code, amountCents: best.savings } : null,
    taxCents,
    totalCents,
    formattedTotal: formatCents(totalCents),
  }

  capture(cart.customerId, 'invoice_created', {
    subtotal_cents: subtotalCents,
    discount_code: invoice.discount?.code ?? null,
    discount_cents: discountCents,
    tax_cents: taxCents,
    total_cents: totalCents,
  })
  if (invoice.discount) {
    capture(cart.customerId, 'discount_applied', {
      code: invoice.discount.code,
      savings_cents: invoice.discount.amountCents,
    })
  }
  return invoice
}
