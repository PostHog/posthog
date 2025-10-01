export interface FeedbackItem {
    id: string
    user: string
    message: string
    type: 'question' | 'feature request' | 'bug'
    timestamp: string
}
