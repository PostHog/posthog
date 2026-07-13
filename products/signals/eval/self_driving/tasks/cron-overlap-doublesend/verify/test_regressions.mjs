// Catches: an overlap-guard fix that breaks normal digest behavior - single-run sends, per-period idempotency, next-period sends (guard never released), recipient dedupe, or body rendering.
import assert from 'node:assert/strict'
import test from 'node:test'

import { periodKey, renderDigestBody, runDigest } from '../src/digest.js'
import { dedupeRecipients } from '../src/recipients.js'

const tick = () => new Promise((resolve) => setImmediate(resolve))

class FakeStore {
  constructor(subscriptions, itemsByUser = {}) {
    this.subscriptions = subscriptions
    this.itemsByUser = itemsByUser
    this.sent = new Map()
  }

  async getDueSubscriptions(period) {
    await tick()
    return this.subscriptions.filter((sub) => sub.active && this.sent.get(sub.id) !== period)
  }

  async getDigestItems(userId, period) {
    await tick()
    return (this.itemsByUser[userId] ?? []).filter((item) => item.period === period)
  }

  async markSent(subscriptionId, period) {
    await tick()
    this.sent.set(subscriptionId, period)
  }
}

class FakeMailer {
  constructor() {
    this.messages = []
  }

  async send(message) {
    await tick()
    this.messages.push(message)
  }
}

function makeDeps() {
  const subscriptions = [
    { id: 'sub-1', userId: 'u-ana', email: 'ana@acme.test', active: true },
    { id: 'sub-2', userId: 'u-ana', email: 'ANA@acme.test', active: true }, // same person via second project
    { id: 'sub-3', userId: 'u-ben', email: 'ben@acme.test', active: true },
    { id: 'sub-4', userId: 'u-mel', email: 'mel@acme.test', active: false },
  ]
  const itemsByUser = {
    'u-ana': [{ period: '2026-07-10', title: '3 new comments on your report' }],
    'u-ben': [],
  }
  return { store: new FakeStore(subscriptions, itemsByUser), mailer: new FakeMailer() }
}

const now = () => new Date('2026-07-10T06:00:00Z')
const nextDay = () => new Date('2026-07-11T06:00:00Z')

test('a single run sends one digest per unique active recipient', async () => {
  const { store, mailer } = makeDeps()
  const result = await runDigest({ store, mailer, now })
  const recipients = mailer.messages.map((message) => message.to.toLowerCase()).sort()
  assert.deepEqual(recipients, ['ana@acme.test', 'ben@acme.test'])
  assert.equal(result.sent, 2)
  const anaMessage = mailer.messages.find((message) => message.to.toLowerCase() === 'ana@acme.test')
  assert.match(anaMessage.subject, /2026-07-10/)
  assert.match(anaMessage.body, /3 new comments/)
})

test('a sequential second run in the same period sends nothing', async () => {
  const { store, mailer } = makeDeps()
  await runDigest({ store, mailer, now })
  const before = mailer.messages.length
  await runDigest({ store, mailer, now })
  assert.equal(mailer.messages.length, before)
})

test('the next period sends again', async () => {
  const { store, mailer } = makeDeps()
  await runDigest({ store, mailer, now })
  const result = await runDigest({ store, mailer, now: nextDay })
  assert.equal(result.sent, 2)
})

test('dedupeRecipients keeps one entry per case-insensitive email', () => {
  const deduped = dedupeRecipients([
    { id: 'sub-1', email: 'ana@acme.test' },
    { id: 'sub-2', email: 'ANA@acme.test' },
    { id: 'sub-3', email: 'ben@acme.test' },
  ])
  assert.equal(deduped.length, 2)
  const emails = deduped.map((sub) => sub.email.toLowerCase())
  assert.deepEqual([...new Set(emails)].sort(), ['ana@acme.test', 'ben@acme.test'])
})

test('digest body renders items and the empty state', () => {
  assert.equal(renderDigestBody([]), 'Nothing new today.')
  assert.equal(renderDigestBody([{ title: 'One thing' }]), '- One thing')
  assert.equal(periodKey(new Date('2026-07-10T23:59:59Z')), '2026-07-10')
})
