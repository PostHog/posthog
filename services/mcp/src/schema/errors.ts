import { z } from 'zod'

export enum OrderByErrors {
    Occurrences = 'occurrences',
    FirstSeen = 'first_seen',
    LastSeen = 'last_seen',
    Users = 'users',
    Sessions = 'sessions',
}

export enum OrderDirectionErrors {
    Ascending = 'ASC',
    Descending = 'DESC',
}

export enum StatusErrors {
    Active = 'active',
    Resolved = 'resolved',
    Archived = 'archived',
    Suppressed = 'suppressed',
    PendingRelease = 'pending_release',
    All = 'all',
}

export enum IssueStatus {
    Active = 'active',
    Resolved = 'resolved',
    Archived = 'archived',
    Suppressed = 'suppressed',
    PendingRelease = 'pending_release',
}

export const UpdateIssueStatusSchema = z.object({
    issueId: z.string().uuid().describe('The ID of the error tracking issue to update'),
    status: z
        .nativeEnum(IssueStatus)
        .describe('The new status for the issue: active, resolved, archived, suppressed, or pending_release'),
})

export const ListErrorsSchema = z.object({
    orderBy: z.nativeEnum(OrderByErrors).optional(),
    dateFrom: z.string().datetime().optional(),
    dateTo: z.string().datetime().optional(),
    orderDirection: z.nativeEnum(OrderDirectionErrors).optional(),
    filterTestAccounts: z.boolean().optional(),
    status: z.nativeEnum(StatusErrors).optional(),
})

export const ErrorDetailsSchema = z.object({
    issueId: z.string(),
    dateFrom: z.string().datetime().optional(),
    dateTo: z.string().datetime().optional(),
})

export type ListErrorsData = z.infer<typeof ListErrorsSchema>

export type ErrorDetailsData = z.infer<typeof ErrorDetailsSchema>
