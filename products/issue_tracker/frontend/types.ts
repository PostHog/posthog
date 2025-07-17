export enum IssueStatus {
    BACKLOG = 'backlog',
    TODO = 'todo',
    IN_PROGRESS = 'in_progress',
    TESTING = 'testing',
    DONE = 'done',
}

export enum OriginProduct {
    ERROR_TRACKING = 'error_tracking',
    EVAL_CLUSTERS = 'eval_clusters',
    USER_CREATED = 'user_created',
    SUPPORT_QUEUE = 'support_queue',
}

export interface Issue {
    id: string
    title: string
    description: string
    status: IssueStatus
    originProduct: OriginProduct
    priority: number
    position: number
    createdAt: string
    updatedAt: string
}

export interface KanbanColumn {
    id: IssueStatus
    title: string
    issues: Issue[]
}
