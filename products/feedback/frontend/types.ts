export enum FeedbackStatus {
    Visible = 'visible',
    Hidden = 'hidden',
}

export enum FeedbackType {
    Question = 'question',
    Feedback = 'feedback',
    Bug = 'bug',
}

export interface FeedbackItem {
    id: string
    user: string
    message: string
    type: FeedbackType
    timestamp: string
    status: FeedbackStatus
}
