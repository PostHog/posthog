export enum FeedbackStatus {
    Visible = 'visible',
    Hidden = 'hidden',
}

export interface FeedbackItem {
    id: string
    user: string
    message: string
    type: 'question' | 'feature request' | 'bug'
    timestamp: string
    status: FeedbackStatus
}
