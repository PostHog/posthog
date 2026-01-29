import { z } from 'zod'

export const AnnotationScopeEnum = z.enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])

export const AnnotationCreationTypeEnum = z.enum(['USR', 'GIT'])

export const AnnotationSchema = z.object({
    id: z.number(),
    content: z.string().nullable(),
    date_marker: z.string().datetime().nullable(),
    creation_type: AnnotationCreationTypeEnum,
    dashboard_item: z.number().nullable().describe('Dashboard item (insight) ID'),
    dashboard_id: z.number().nullable().describe('Dashboard ID'),
    dashboard_name: z.string().nullable(),
    insight_short_id: z.string().nullable(),
    insight_name: z.string().nullable(),
    insight_derived_name: z.string().nullable(),
    created_by: z
        .object({
            id: z.number(),
            uuid: z.string(),
            distinct_id: z.string().nullable(),
            first_name: z.string(),
            last_name: z.string(),
            email: z.string(),
        })
        .passthrough(),
    created_at: z.string().datetime(),
    updated_at: z.string().datetime(),
    deleted: z.boolean(),
    scope: AnnotationScopeEnum,
})

export const SimpleAnnotationSchema = AnnotationSchema.pick({
    id: true,
    content: true,
    date_marker: true,
    scope: true,
    created_at: true,
    created_by: true,
})

export const CreateAnnotationInputSchema = z.object({
    content: z
        .string()
        .describe('Annotation content - text describing the event or marker'),
    date_marker: z
        .string()
        .datetime()
        .describe('ISO 8601 datetime string of when the event occurred'),
    scope: AnnotationScopeEnum
        .describe(
            'Scope of the annotation: dashboard_item (insight), dashboard, project, organization, or recording'
        ),
    dashboard_item: z
        .number()
        .nullable()
        .optional()
        .describe('Dashboard item (insight) ID if scope is dashboard_item'),
    dashboard_id: z
        .number()
        .nullable()
        .optional()
        .describe('Dashboard ID if scope is dashboard'),
    creation_type: AnnotationCreationTypeEnum
        .optional()
        .describe('How the annotation was created (USR for user, GIT for GitHub)'),
})

export const UpdateAnnotationInputSchema = z.object({
    content: z
        .string()
        .optional()
        .describe('Update annotation content'),
    date_marker: z
        .string()
        .datetime()
        .optional()
        .describe('Update the date marker'),
    scope: AnnotationScopeEnum
        .optional()
        .describe('Update the scope'),
    dashboard_item: z
        .number()
        .nullable()
        .optional()
        .describe('Update dashboard item ID'),
    dashboard_id: z
        .number()
        .nullable()
        .optional()
        .describe('Update dashboard ID'),
})

export const ListAnnotationsSchema = z.object({
    limit: z
        .number()
        .int()
        .positive()
        .optional()
        .describe('Maximum number of annotations to return'),
    offset: z
        .number()
        .int()
        .min(0)
        .optional()
        .describe('Number of annotations to skip'),
    scope: AnnotationScopeEnum
        .optional()
        .describe('Filter by scope'),
    dashboard_id: z
        .number()
        .optional()
        .describe('Filter by dashboard ID'),
    dashboard_item: z
        .number()
        .optional()
        .describe('Filter by dashboard item (insight) ID'),
    deleted: z
        .boolean()
        .optional()
        .describe('Filter by deleted status'),
})

export type AnnotationScope = z.infer<typeof AnnotationScopeEnum>
export type AnnotationCreationType = z.infer<typeof AnnotationCreationTypeEnum>
export type Annotation = z.infer<typeof AnnotationSchema>
export type SimpleAnnotation = z.infer<typeof SimpleAnnotationSchema>
export type CreateAnnotationInput = z.infer<typeof CreateAnnotationInputSchema>
export type UpdateAnnotationInput = z.infer<typeof UpdateAnnotationInputSchema>
export type ListAnnotationsData = z.infer<typeof ListAnnotationsSchema>
