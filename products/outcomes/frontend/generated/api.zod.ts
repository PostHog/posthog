/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create, read, update, and delete outcome definitions, and inspect who reached them.
 */
export const outcomesCreateBodyNameMax = 400

export const outcomesCreateBodyCriteriaOnePathsItemAtomsItemEventMax = 400

export const outcomesCreateBodyCriteriaOnePathsItemAtomsItemAggregationDefault = `count`
export const outcomesCreateBodyCriteriaOnePathsItemAtomsItemAggregationPropertyMax = 400

export const outcomesCreateBodyCriteriaOnePathsItemAtomsItemThresholdDefault = 1

export const OutcomesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(outcomesCreateBodyNameMax).describe('Human-readable name of the outcome.'),
    description: zod.string().optional().describe('What reaching this outcome means for the business.'),
    criteria: zod
        .object({
            paths: zod
                .array(
                    zod.object({
                        atoms: zod
                            .array(
                                zod.object({
                                    event: zod
                                        .string()
                                        .max(outcomesCreateBodyCriteriaOnePathsItemAtomsItemEventMax)
                                        .describe('Name of the event this condition aggregates.'),
                                    properties: zod
                                        .array(
                                            zod
                                                .record(zod.string(), zod.unknown())
                                                .describe(
                                                    'A standard PostHog property filter (event property, person property, cohort, HogQL, ...), in the same shape the insights API accepts.'
                                                )
                                        )
                                        .optional()
                                        .describe(
                                            'Property filters an event must match to count toward this condition.'
                                        ),
                                    aggregation: zod
                                        .enum(['count', 'sum', 'distinct'])
                                        .describe('\* `count` - count\n\* `sum` - sum\n\* `distinct` - distinct')
                                        .default(outcomesCreateBodyCriteriaOnePathsItemAtomsItemAggregationDefault)
                                        .describe(
                                            'Monotone aggregation over matching events: count of events, sum of a numeric property (the highest running total, so refunds never un-reach it), or number of distinct values of a property.\n\n\* `count` - count\n\* `sum` - sum\n\* `distinct` - distinct'
                                        ),
                                    aggregation_property: zod
                                        .string()
                                        .max(outcomesCreateBodyCriteriaOnePathsItemAtomsItemAggregationPropertyMax)
                                        .nullish()
                                        .describe(
                                            'Event property to sum or count distinct values of; required for sum and distinct, must be empty for count.'
                                        ),
                                    threshold: zod
                                        .number()
                                        .default(outcomesCreateBodyCriteriaOnePathsItemAtomsItemThresholdDefault)
                                        .describe(
                                            'The condition is satisfied once the aggregation reaches at least this value. Must be a whole number of at least 1 for count and distinct, greater than 0 for sum.'
                                        ),
                                })
                            )
                            .describe(
                                'Conditions combined within this path; all must be met unless min_matches is set.'
                            ),
                        min_matches: zod
                            .number()
                            .min(1)
                            .nullish()
                            .describe(
                                'Satisfy the path when at least this many of its conditions are met (M-of-N). Leave empty to require all of them.'
                            ),
                    })
                )
                .describe("Paths OR'd together: a person reaches the outcome by completing any one path."),
        })
        .describe("Monotone criteria: paths OR'd together, conditions AND'd within a path (optionally M-of-N)."),
})

/**
 * Create, read, update, and delete outcome definitions, and inspect who reached them.
 */
export const outcomesUpdateBodyNameMax = 400

export const outcomesUpdateBodyCriteriaOnePathsItemAtomsItemEventMax = 400

export const outcomesUpdateBodyCriteriaOnePathsItemAtomsItemAggregationDefault = `count`
export const outcomesUpdateBodyCriteriaOnePathsItemAtomsItemAggregationPropertyMax = 400

export const outcomesUpdateBodyCriteriaOnePathsItemAtomsItemThresholdDefault = 1

export const OutcomesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(outcomesUpdateBodyNameMax).describe('Human-readable name of the outcome.'),
    description: zod.string().optional().describe('What reaching this outcome means for the business.'),
    criteria: zod
        .object({
            paths: zod
                .array(
                    zod.object({
                        atoms: zod
                            .array(
                                zod.object({
                                    event: zod
                                        .string()
                                        .max(outcomesUpdateBodyCriteriaOnePathsItemAtomsItemEventMax)
                                        .describe('Name of the event this condition aggregates.'),
                                    properties: zod
                                        .array(
                                            zod
                                                .record(zod.string(), zod.unknown())
                                                .describe(
                                                    'A standard PostHog property filter (event property, person property, cohort, HogQL, ...), in the same shape the insights API accepts.'
                                                )
                                        )
                                        .optional()
                                        .describe(
                                            'Property filters an event must match to count toward this condition.'
                                        ),
                                    aggregation: zod
                                        .enum(['count', 'sum', 'distinct'])
                                        .describe('\* `count` - count\n\* `sum` - sum\n\* `distinct` - distinct')
                                        .default(outcomesUpdateBodyCriteriaOnePathsItemAtomsItemAggregationDefault)
                                        .describe(
                                            'Monotone aggregation over matching events: count of events, sum of a numeric property (the highest running total, so refunds never un-reach it), or number of distinct values of a property.\n\n\* `count` - count\n\* `sum` - sum\n\* `distinct` - distinct'
                                        ),
                                    aggregation_property: zod
                                        .string()
                                        .max(outcomesUpdateBodyCriteriaOnePathsItemAtomsItemAggregationPropertyMax)
                                        .nullish()
                                        .describe(
                                            'Event property to sum or count distinct values of; required for sum and distinct, must be empty for count.'
                                        ),
                                    threshold: zod
                                        .number()
                                        .default(outcomesUpdateBodyCriteriaOnePathsItemAtomsItemThresholdDefault)
                                        .describe(
                                            'The condition is satisfied once the aggregation reaches at least this value. Must be a whole number of at least 1 for count and distinct, greater than 0 for sum.'
                                        ),
                                })
                            )
                            .describe(
                                'Conditions combined within this path; all must be met unless min_matches is set.'
                            ),
                        min_matches: zod
                            .number()
                            .min(1)
                            .nullish()
                            .describe(
                                'Satisfy the path when at least this many of its conditions are met (M-of-N). Leave empty to require all of them.'
                            ),
                    })
                )
                .describe("Paths OR'd together: a person reaches the outcome by completing any one path."),
        })
        .describe("Monotone criteria: paths OR'd together, conditions AND'd within a path (optionally M-of-N)."),
})

/**
 * Create, read, update, and delete outcome definitions, and inspect who reached them.
 */
export const outcomesPartialUpdateBodyNameMax = 400

export const outcomesPartialUpdateBodyCriteriaOnePathsItemAtomsItemEventMax = 400

export const outcomesPartialUpdateBodyCriteriaOnePathsItemAtomsItemAggregationDefault = `count`
export const outcomesPartialUpdateBodyCriteriaOnePathsItemAtomsItemAggregationPropertyMax = 400

export const outcomesPartialUpdateBodyCriteriaOnePathsItemAtomsItemThresholdDefault = 1

export const OutcomesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(outcomesPartialUpdateBodyNameMax).optional().describe('Human-readable name of the outcome.'),
    description: zod.string().optional().describe('What reaching this outcome means for the business.'),
    criteria: zod
        .object({
            paths: zod
                .array(
                    zod.object({
                        atoms: zod
                            .array(
                                zod.object({
                                    event: zod
                                        .string()
                                        .max(outcomesPartialUpdateBodyCriteriaOnePathsItemAtomsItemEventMax)
                                        .describe('Name of the event this condition aggregates.'),
                                    properties: zod
                                        .array(
                                            zod
                                                .record(zod.string(), zod.unknown())
                                                .describe(
                                                    'A standard PostHog property filter (event property, person property, cohort, HogQL, ...), in the same shape the insights API accepts.'
                                                )
                                        )
                                        .optional()
                                        .describe(
                                            'Property filters an event must match to count toward this condition.'
                                        ),
                                    aggregation: zod
                                        .enum(['count', 'sum', 'distinct'])
                                        .describe('\* `count` - count\n\* `sum` - sum\n\* `distinct` - distinct')
                                        .default(
                                            outcomesPartialUpdateBodyCriteriaOnePathsItemAtomsItemAggregationDefault
                                        )
                                        .describe(
                                            'Monotone aggregation over matching events: count of events, sum of a numeric property (the highest running total, so refunds never un-reach it), or number of distinct values of a property.\n\n\* `count` - count\n\* `sum` - sum\n\* `distinct` - distinct'
                                        ),
                                    aggregation_property: zod
                                        .string()
                                        .max(
                                            outcomesPartialUpdateBodyCriteriaOnePathsItemAtomsItemAggregationPropertyMax
                                        )
                                        .nullish()
                                        .describe(
                                            'Event property to sum or count distinct values of; required for sum and distinct, must be empty for count.'
                                        ),
                                    threshold: zod
                                        .number()
                                        .default(outcomesPartialUpdateBodyCriteriaOnePathsItemAtomsItemThresholdDefault)
                                        .describe(
                                            'The condition is satisfied once the aggregation reaches at least this value. Must be a whole number of at least 1 for count and distinct, greater than 0 for sum.'
                                        ),
                                })
                            )
                            .describe(
                                'Conditions combined within this path; all must be met unless min_matches is set.'
                            ),
                        min_matches: zod
                            .number()
                            .min(1)
                            .nullish()
                            .describe(
                                'Satisfy the path when at least this many of its conditions are met (M-of-N). Leave empty to require all of them.'
                            ),
                    })
                )
                .describe("Paths OR'd together: a person reaches the outcome by completing any one path."),
        })
        .optional()
        .describe("Monotone criteria: paths OR'd together, conditions AND'd within a path (optionally M-of-N)."),
})
