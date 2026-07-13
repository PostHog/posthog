import { readFile, writeFile } from 'node:fs/promises'

export class SubscriptionStore {
  constructor({ subscriptionsFile, activityFile }) {
    this.subscriptionsFile = subscriptionsFile
    this.activityFile = activityFile
  }

  async #readSubscriptions() {
    return JSON.parse(await readFile(this.subscriptionsFile, 'utf8'))
  }

  async getDueSubscriptions(period) {
    const rows = await this.#readSubscriptions()
    return rows.filter((row) => row.active && row.lastSentPeriod !== period)
  }

  async getDigestItems(userId, period) {
    const activity = JSON.parse(await readFile(this.activityFile, 'utf8'))
    const items = activity[userId] ?? []
    return items.filter((item) => item.period === period)
  }

  async markSent(subscriptionId, period) {
    const rows = await this.#readSubscriptions()
    const row = rows.find((candidate) => candidate.id === subscriptionId)
    if (row) {
      row.lastSentPeriod = period
      await writeFile(this.subscriptionsFile, JSON.stringify(rows, null, 2))
    }
  }
}
