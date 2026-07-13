import { capture } from './analytics.js'
import { dedupeRecipients } from './recipients.js'

export function periodKey(date) {
  return date.toISOString().slice(0, 10)
}

export function renderDigestBody(items) {
  if (items.length === 0) {
    return 'Nothing new today.'
  }
  return items.map((item) => `- ${item.title}`).join('\n')
}

export async function runDigest({ store, mailer, now = () => new Date() }) {
  const period = periodKey(now())
  const startedAt = Date.now()
  capture('system', 'digest_run_started', { period })

  const due = await store.getDueSubscriptions(period)
  const recipients = dedupeRecipients(due)
  let sent = 0
  for (const subscription of recipients) {
    const items = await store.getDigestItems(subscription.userId, period)
    await mailer.send({
      to: subscription.email,
      subject: `Your Acme digest for ${period}`,
      body: renderDigestBody(items),
    })
    // Mark every subscription behind this address, so deduped rows are settled too.
    const email = subscription.email.trim().toLowerCase()
    for (const row of due) {
      if (row.email.trim().toLowerCase() === email) {
        await store.markSent(row.id, period)
      }
    }
    capture(subscription.userId, 'digest_sent', { period, item_count: items.length })
    sent += 1
  }

  capture('system', 'digest_run_completed', { period, sent, duration_ms: Date.now() - startedAt })
  return { period, sent }
}
