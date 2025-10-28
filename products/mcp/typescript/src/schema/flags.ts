import { z } from 'zod'

export interface PostHogFeatureFlag {
    id: number
    key: string
    name: string
}

export interface PostHogFlagsResponse {
    results?: PostHogFeatureFlag[]
}
const base = ['exact', 'is_not', 'is_set', 'is_not_set'] as const
const stringOps = [
    ...base,
    'icontains',
    'not_icontains',
    'regex',
    'not_regex',
    'is_cleaned_path_exact',
] as const
const numberOps = [...base, 'gt', 'gte', 'lt', 'lte', 'min', 'max'] as const
const booleanOps = [...base] as const

const arrayOps = ['in', 'not_in'] as const

const operatorSchema = z.enum([
    ...stringOps,
    ...numberOps,
    ...booleanOps,
    ...arrayOps,
] as unknown as [string, ...string[]])

export const PersonPropertyFilterSchema = z
    .object({
        key: z.string(),
        value: z.union([
            z.string(),
            z.number(),
            z.boolean(),
            z.array(z.string()),
            z.array(z.number()),
        ]),
        operator: operatorSchema.optional(),
    })
    .superRefine((data, ctx) => {
        const { value, operator } = data
        if (!operator) {
            return
        }

        let valid = false

        if (typeof value === 'string') {
            valid = stringOps.includes(operator as any)
        } else if (typeof value === 'number') {
            valid = numberOps.includes(operator as any)
        } else if (typeof value === 'boolean') {
            valid = booleanOps.includes(operator as any)
        } else if (Array.isArray(value)) {
            if (value.length === 0) {
                valid = arrayOps.includes(operator as any)
            } else {
                const elementType = typeof value[0]
                if (elementType === 'string') {
                    // String arrays can use string operators (exact, icontains, etc.) + array operators (in, not_in)
                    valid = stringOps.includes(operator as any) || arrayOps.includes(operator as any)
                } else if (elementType === 'number') {
                    // Number arrays can use base operators (exact, is_not, etc.) + array operators, but not comparisons (gt, gte, etc.)
                    valid = base.includes(operator as any) || arrayOps.includes(operator as any)
                }
            }
        }

        if (!valid) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                message: `operator "${operator}" is not valid for value type "${Array.isArray(value) ? 'array' : typeof value}"`,
            })
        }

        if (!Array.isArray(value) && arrayOps.includes(operator as any)) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                message: `operator "${operator}" requires an array value`,
            })
        }
    })
    .transform((data) => {
        // when using is_set or is_not_set, set the value the same as the operator
        if (data.operator === 'is_set' || data.operator === 'is_not_set') {
            data.value = data.operator
        }

        return {
            ...data,
            type: 'person',
        }
    })

export type PersonPropertyFilter = z.infer<typeof PersonPropertyFilterSchema>

export const FiltersSchema = z.object({
    properties: z.array(PersonPropertyFilterSchema),
    rollout_percentage: z.number(),
})

export type Filters = z.infer<typeof FiltersSchema>

export const FilterGroupsSchema = z.object({
    groups: z.array(FiltersSchema),
})

export type FilterGroups = z.infer<typeof FilterGroupsSchema>

export const CreateFeatureFlagInputSchema = z.object({
    name: z.string(),
    key: z.string(),
    description: z.string(),
    filters: FilterGroupsSchema,
    active: z.boolean(),
    tags: z.array(z.string()).optional(),
})

export type CreateFeatureFlagInput = z.infer<typeof CreateFeatureFlagInputSchema>

export const UpdateFeatureFlagInputSchema = CreateFeatureFlagInputSchema.omit({
    key: true,
}).partial()

export type UpdateFeatureFlagInput = z.infer<typeof UpdateFeatureFlagInputSchema>

export const FeatureFlagSchema = z.object({
    id: z.number(),
    key: z.string(),
    name: z.string(),
    description: z.string().nullish(),
    filters: z.any().nullish(),
    active: z.boolean(),
    tags: z.array(z.string()).optional(),
})

export type FeatureFlag = z.infer<typeof FeatureFlagSchema>
