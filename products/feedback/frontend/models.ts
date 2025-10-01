export interface FeedbackItemCategory {
    id: string
    name: string
}

export interface FeedbackItemStatus {
    id: string
    name: string
}

export interface FeedbackItemTopic {
    id: string
    name: string
}

export interface FeedbackItemAssignment {
    user: number | null
    role: number | null
}

export interface FeedbackItem {
    id: string
    content: string
    category: FeedbackItemCategory | null
    topic: FeedbackItemTopic | null
    status: FeedbackItemStatus | null
    assignment: FeedbackItemAssignment | null
    attachments: string[]
    created_at: string
}
