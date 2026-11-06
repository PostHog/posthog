import type { LemonTagType } from '@posthog/lemon-ui'

import type { ReceivedEmailApi } from 'products/workflows/frontend/generated/api.schemas'

export const FILTER_REASON_LABEL: Record<string, string> = {
    spam: 'Spam',
    auto_reply: 'Auto-reply',
    rate_limited: 'Too many from this sender',
}

export const FILTER_REASON_DESCRIPTION: Record<string, string> = {
    spam: "The spam scan flagged this email, so it didn't fire an event. It doesn't count against anything.",
    auto_reply:
        "A machine wrote this, such as an out-of-office or a bounce, so it didn't fire an event. This keeps workflows from answering each other in a loop.",
    rate_limited:
        "This sender wrote too many emails in the past hour, so this one didn't fire an event. This keeps workflows from answering each other in a loop.",
}

export const VERDICT_LABEL: Record<string, string> = {
    pass: 'Pass',
    fail: 'Fail',
    gray: 'Not checked',
    processing_failed: 'Check failed',
}

export function verdictTagType(verdict: string): LemonTagType {
    return verdict === 'pass' ? 'success' : verdict === 'fail' ? 'danger' : 'muted'
}

export function senderLabel(email: Pick<ReceivedEmailApi, 'from_address' | 'from_name'>): string {
    return email.from_name || email.from_address || 'Unknown sender'
}

export function formatBytes(bytes: number): string {
    if (bytes < 1024) {
        return `${bytes} B`
    }
    return bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
