export interface FeedbackItemCategory {
    id: string
    name: string
    statuses?: FeedbackItemStatus[]
}

export interface FeedbackItemStatus {
    id: string
    name: string
    category?: string
}

export interface FeedbackItemTopic {
    id: string
    name: string
}

export interface FeedbackItemAssignment {
    user: {
        id: number
        uuid: string
        distinct_id: string
        first_name: string
        last_name: string
        email: string
    } | null
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
