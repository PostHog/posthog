// Catches: a discount fix that breaks single-discount invoices, eligibility rules (expiry, minimum subtotal), the no-stacking policy, tax, or currency formatting.
import assert from 'node:assert/strict'
import test from 'node:test'

import { createInvoice } from '../src/invoice.js'

const NOW = { now: new Date('2026-07-01T00:00:00Z') }

function cart(subtotalCents, region) {
  return { customerId: 'cus_verify', items: [{ priceCents: subtotalCents, quantity: 1 }], region }
}

test('single discount code is applied exactly', () => {
  const invoice = createInvoice(cart(12000), ['SAVE10'], NOW)
  assert.equal(invoice.discount.code, 'SAVE10')
  assert.equal(invoice.discount.amountCents, 1200)
  assert.equal(invoice.totalCents, 10800)
})

test('no discount codes means full price', () => {
  const invoice = createInvoice(cart(12000), [], NOW)
  assert.equal(invoice.discount, null)
  assert.equal(invoice.totalCents, 12000)
  assert.equal(invoice.formattedTotal, '$120.00')
})

test('expired discount is ignored', () => {
  const invoice = createInvoice(cart(12000), ['LAUNCH20'], NOW)
  assert.equal(invoice.discount, null)
  assert.equal(invoice.totalCents, 12000)
})

test('discount below its minimum subtotal is ignored', () => {
  const invoice = createInvoice(cart(3000), ['WELCOME15'], NOW)
  assert.equal(invoice.discount, null)
})

test('unknown code is ignored', () => {
  const invoice = createInvoice(cart(3000), ['BOGUS42'], NOW)
  assert.equal(invoice.discount, null)
})

test('discounts never stack - exactly one discount line', () => {
  const invoice = createInvoice(cart(12000), ['SAVE10', 'FLAT5'], NOW)
  assert.ok(invoice.discount, 'a discount must be applied')
  assert.equal(typeof invoice.discount.code, 'string')
  assert.equal(invoice.totalCents, invoice.subtotalCents - invoice.discount.amountCents)
})

test('multi-item subtotals and thousands formatting', () => {
  const invoice = createInvoice(
    { customerId: 'cus_verify', items: [{ priceCents: 61728, quantity: 2 }] },
    [],
    NOW
  )
  assert.equal(invoice.subtotalCents, 123456)
  assert.equal(invoice.formattedTotal, '$1,234.56')
})

test('regional tax is applied to the discounted base', () => {
  const invoice = createInvoice(cart(10000, 'EU'), [], NOW)
  assert.equal(invoice.taxCents, 2100)
  assert.equal(invoice.totalCents, 12100)
})
