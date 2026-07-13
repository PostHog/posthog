import { initAnalytics } from './analytics.js'
import { config } from './config.js'
import { runDigest } from './digest.js'
import { SmtpMailer } from './mailer.js'
import { startScheduler } from './scheduler.js'
import { SubscriptionStore } from './store.js'

async function main() {
  await initAnalytics()
  const store = new SubscriptionStore({
    subscriptionsFile: config.subscriptionsFile,
    activityFile: config.activityFile,
  })
  const mailer = new SmtpMailer({ host: config.smtpHost, port: config.smtpPort })
  const deps = { store, mailer }

  await runDigest(deps)
  startScheduler(deps, config.digestIntervalMs)
  console.log(`acme-notifier scheduling digests every ${config.digestIntervalMs}ms`)
}

main()
