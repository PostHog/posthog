// Catches: best-of discount selection applying the WORST eligible discount (ascending savings sort + take-first) instead of the best one.
import assert from 'node:assert/strict'
import test from 'node:test'

import { createInvoice } from '../src/invoice.js'

const NOW = { now: new Date('2026-07-01T00:00:00Z') }

function cart(subtotalCents) {
  return { customerId: 'cus_verify', items: [{ priceCents: subtotalCents, quantity: 1 }] }
}

test('percent discount beats a smaller flat discount', () => {
  // $120 order: SAVE10 saves $12, FLAT5 saves $5 - SAVE10 must win.
  const invoice = createInvoice(cart(12000), ['SAVE10', 'FLAT5'], NOW)
  assert.equal(invoice.discount.code, 'SAVE10')
  assert.equal(invoice.discount.amountCents, 1200)
  assert.equal(invoice.totalCents, 10800)
  assert.equal(invoice.formattedTotal, '$108.00')
})

test('flat discount beats a smaller percent discount on small carts', () => {
  // $30 order: FLAT5 saves $5, SAVE10 saves $3 - FLAT5 must win.
  const invoice = createInvoice(cart(3000), ['FLAT5', 'SAVE10'], NOW)
  assert.equal(invoice.discount.code, 'FLAT5')
  assert.equal(invoice.discount.amountCents, 500)
  assert.equal(invoice.totalCents, 2500)
})

test('the larger of two percent discounts wins', () => {
  // $80 order: WELCOME15 saves $12, SAVE10 saves $8 - WELCOME15 must win.
  const invoice = createInvoice(cart(8000), ['SAVE10', 'WELCOME15'], NOW)
  assert.equal(invoice.discount.code, 'WELCOME15')
  assert.equal(invoice.discount.amountCents, 1200)
  assert.equal(invoice.totalCents, 6800)
})
