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
    All = 'all',
    Suppressed = 'suppressed',
}

export const ListErrorsSchema = z.object({
    orderBy: z.nativeEnum(OrderByErrors).optional(),
    dateFrom: z.string().datetime().optional(),
    dateTo: z.string().datetime().optional(),
    orderDirection: z.nativeEnum(OrderDirectionErrors).optional(),
    filterTestAccounts: z.boolean().optional(),
    status: z.nativeEnum(StatusErrors).optional(),
})

export const ErrorDetailsSchema = z.object({
    issueId: z.string().uuid(),
    dateFrom: z.string().datetime().optional(),
    dateTo: z.string().datetime().optional(),
})

export const UpdateIssueStatusSchema = z.enum(['active', 'resolved', 'suppressed'])

export const UpdateIssueSchema = z.object({
    status: UpdateIssueStatusSchema.optional(),
    name: z.string().optional(),
})

export const IssueSchema = z.object({
    id: z.string().uuid(),
    status: UpdateIssueStatusSchema,
    name: z.string(),
    description: z.string().nullish(),
    first_seen: z.string().datetime(),
})

export type ListErrorsData = z.infer<typeof ListErrorsSchema>

export type ErrorDetailsData = z.infer<typeof ErrorDetailsSchema>

export type UpdateIssueData = z.infer<typeof UpdateIssueSchema>

export type Issue = z.infer<typeof IssueSchema>
