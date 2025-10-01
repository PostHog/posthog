export enum FeedbackStatus {
    Visible = 'visible',
    Hidden = 'hidden',
}

export interface FeedbackItem {
    id: string
    user: string
    message: string
    category: string
    topic: string
    timestamp: string
    status: FeedbackStatus
}

export type StatusOption = FeedbackStatus | 'all'
