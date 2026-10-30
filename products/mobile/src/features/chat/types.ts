import type { ChatObjectContext } from './objectContext'

export interface ChatReportContext {
    reportId: string
    title: string
    webUrl?: string
    canAct: boolean
}

export interface ChatInboxContextItem {
    reportId: string
    title: string
}

export type ChatContext =
    | { kind: 'reports'; reports: ChatReportContext[] }
    | { kind: 'inbox'; items: ChatInboxContextItem[] }
    | { kind: 'object'; item: ChatObjectContext }
    | { kind: 'none' }

export interface ChatError {
    kind:
        | 'credits'
        | 'throttled'
        | 'busy'
        | 'unavailable'
        | 'not_found'
        | 'invalid'
        | 'auth'
        | 'access'
        | 'network'
        | 'unknown'
    message: string
    retryAfterSeconds?: number
}
