export const config = {
  digestIntervalMs: Number(process.env.DIGEST_INTERVAL_MS ?? 60 * 60 * 1000),
  smtpHost: process.env.SMTP_HOST ?? 'localhost',
  smtpPort: Number(process.env.SMTP_PORT ?? 2525),
  subscriptionsFile: process.env.SUBSCRIPTIONS_FILE ?? 'data/subscriptions.json',
  activityFile: process.env.ACTIVITY_FILE ?? 'data/activity.json',
}
