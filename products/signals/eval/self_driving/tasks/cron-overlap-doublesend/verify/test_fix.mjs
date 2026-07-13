// Catches: overlapping runDigest invocations (a scheduler tick firing while the previous run is still in flight) sending each recipient the digest twice.
import assert from 'node:assert/strict'
import test from 'node:test'

import { runDigest } from '../src/digest.js'

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
    this.sends = []
  }

  async send(message) {
    await tick()
    this.sends.push(message.to)
  }
}

test('two concurrent digest runs send at most one email per recipient', async () => {
  const subscriptions = Array.from({ length: 6 }, (_, index) => ({
    id: `sub-${index}`,
    userId: `u-${index}`,
    email: `user${index}@acme.test`,
    active: true,
  }))
  const store = new FakeStore(subscriptions)
  const mailer = new FakeMailer()
  const now = () => new Date('2026-07-10T06:00:00Z')

  // Simulates a scheduler tick firing while the previous (slow) run is still going.
  await Promise.allSettled([
    runDigest({ store, mailer, now }),
    runDigest({ store, mailer, now }),
  ])

  const counts = new Map()
  for (const to of mailer.sends) {
    counts.set(to, (counts.get(to) ?? 0) + 1)
  }
  for (const subscription of subscriptions) {
    assert.equal(
      counts.get(subscription.email) ?? 0,
      1,
      `${subscription.email} received ${counts.get(subscription.email) ?? 0} digests for one period`
    )
  }
  assert.equal(mailer.sends.length, subscriptions.length)
})
