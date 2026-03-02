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
const stringOpsForSchema = ['icontains', 'not_icontains', 'regex', 'not_regex', 'is_cleaned_path_exact']
const stringOps = [...base, ...stringOpsForSchema] as const
const numberOpsForSchema = ['gt', 'gte', 'lt', 'lte', 'min', 'max']
const numberOps = [...base, ...numberOpsForSchema] as const
const booleanOps = [...base] as const

// Note: 'exact' and 'is_not' support arrays too (checks if value is contained in array)
const arrayOps = ['exact', 'is_not'] as const

const operatorValues = [...new Set([...stringOps, ...numberOps, ...booleanOps, ...arrayOps])] as [string, ...string[]]

const operatorSchema = z.enum(operatorValues)

export const PersonPropertyFilterSchema = z
    .object({
        key: z.string(),
        value: z.union([z.string(), z.number(), z.boolean(), z.array(z.string()), z.array(z.number())]),
        operator: operatorSchema.optional(),
    })
    .superRefine((data, ctx) => {
        const { value, operator } = data
        if (!operator) {
            return
        }
        const isArray = Array.isArray(value)

        const valid =
            (typeof value === 'string' && stringOps.includes(operator as any)) ||
            (typeof value === 'number' && numberOps.includes(operator as any)) ||
            (typeof value === 'boolean' && booleanOps.includes(operator as any)) ||
            (isArray && arrayOps.includes(operator as any))

        if (!valid) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                message: `operator "${operator}" is not valid for value type "${isArray ? 'array' : typeof value}"`,
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
    variant: z.string().nullish().describe('Variant key to serve for this condition (for multivariate flags)'),
})

export type Filters = z.infer<typeof FiltersSchema>

export const VariantSchema = z.object({
    key: z.string().describe('Unique identifier for this variant (e.g., "control", "test", "variant_a")'),
    name: z.string().optional().describe('Human-readable name for this variant'),
    rollout_percentage: z
        .number()
        .int()
        .min(0)
        .max(100)
        .describe('Percentage of users who will see this variant (0-100). Must be an integer.'),
})

export type Variant = z.infer<typeof VariantSchema>

export const MultivariateSchema = z
    .object({
        variants: z.array(VariantSchema).min(2, 'At least 2 variants required for multivariate flags'),
    })
    .superRefine((data, ctx) => {
        const sum = data.variants.reduce((acc, v) => acc + v.rollout_percentage, 0)
        if (sum !== 100) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                message: 'Variant rollout percentages must sum to 100',
                path: ['variants'],
            })
        }

        const keys = data.variants.map((v) => v.key)
        const duplicates = keys.filter((key, idx) => keys.indexOf(key) !== idx)
        if (duplicates.length > 0) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                message: `Duplicate variant keys: ${[...new Set(duplicates)].join(', ')}`,
                path: ['variants'],
            })
        }
    })

export type Multivariate = z.infer<typeof MultivariateSchema>

export const FilterGroupsSchema = z
    .object({
        groups: z.array(FiltersSchema).min(1, 'At least one group is required'),
        multivariate: MultivariateSchema.optional().describe('Multivariate configuration with variant definitions'),
    })
    .superRefine((data, ctx) => {
        if (data.multivariate) {
            const variantKeys = new Set(data.multivariate.variants.map((v) => v.key))
            data.groups.forEach((group, idx) => {
                if (group.variant && !variantKeys.has(group.variant)) {
                    ctx.addIssue({
                        code: z.ZodIssueCode.custom,
                        message: `Group ${idx} references variant '${group.variant}' which does not exist in multivariate.variants`,
                        path: ['groups', idx, 'variant'],
                    })
                }
            })
        }
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
    updated_at: z.string().nullish(),
})

export type FeatureFlag = z.infer<typeof FeatureFlagSchema>
