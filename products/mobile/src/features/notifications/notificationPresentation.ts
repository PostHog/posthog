import { asRecord } from '@/lib/records'

import { notificationKind, notificationTarget } from './notificationRouting'

const MAX_RECENT_NOTIFICATIONS = 256
const RECENT_NOTIFICATION_MS = 24 * 60 * 60 * 1000

/** In-memory protection for foreground delivery; background delivery belongs to the OS/server. */
export class NotificationPresentation {
    private accountKey: string | null = null
    private recent = new Map<string, number>()

    shouldPresent(identifier: string, data: unknown, accountKey: string, now: number): boolean {
        if (this.accountKey !== accountKey) {
            this.accountKey = accountKey
            this.recent.clear()
        }
        for (const [key, expiresAt] of this.recent) {
            if (expiresAt <= now) {
                this.recent.delete(key)
            }
        }

        const keys = [`request:${identifier}`]
        const target = notificationTarget(data)
        const record = asRecord(data)
        const kind = notificationKind(data)
        // Turns and questions have no stable occurrence id in today's payload.
        // Deduplicating those by run/report would hide a later real reply or decision.
        if (target && target.projectId !== null && record) {
            const runId = typeof record.taskRunId === 'string' ? record.taskRunId : null
            const messageId = typeof record.messageId === 'string' ? record.messageId : null
            const pullRequestId = typeof record.pullRequestId === 'string' ? record.pullRequestId : null
            const occurrence =
                (target.type === 'task' && ['completed', 'failed', 'cancelled'].includes(kind)) ||
                (target.type === 'report' && ['report_completed', 'report_failed', 'report_cancelled'].includes(kind))
                    ? runId
                    : kind === 'thread_message'
                      ? messageId
                      : target.type === 'report' && kind === 'pull_request_ready'
                        ? pullRequestId
                        : target.type === 'report' && kind === 'report_visible'
                          ? target.id
                          : null
            if (occurrence) {
                keys.push(JSON.stringify([target.projectId, target.type, target.id, kind, occurrence]))
            }
        }
        const duplicate = keys.some((key) => this.recent.has(key))
        for (const key of keys) {
            this.recent.set(key, now + RECENT_NOTIFICATION_MS)
        }
        while (this.recent.size > MAX_RECENT_NOTIFICATIONS) {
            const first = this.recent.keys().next().value
            if (first !== undefined) {
                this.recent.delete(first)
            }
        }
        return !duplicate
    }
}
