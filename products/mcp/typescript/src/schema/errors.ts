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

export type ListErrorsData = z.infer<typeof ListErrorsSchema>

export type ErrorDetailsData = z.infer<typeof ErrorDetailsSchema>
