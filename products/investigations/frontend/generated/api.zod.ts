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

export const investigationsCreateBodyDocumentOneQuestionMax = 500

export const investigationsCreateBodyDocumentOneContextMax = 10000

export const investigationsCreateBodyDocumentOneChecksMax = 4

export const investigationsCreateBodyDocumentOneEvidenceItemIdMax = 128

export const investigationsCreateBodyDocumentOneEvidenceItemReferenceExclusiveMin = 0

export const investigationsCreateBodyDocumentOneEvidenceItemTitleMax = 200

export const investigationsCreateBodyDocumentOneEvidenceItemSqlMax = 10000

export const investigationsCreateBodyDocumentOneEvidenceItemUrlMax = 2000

export const investigationsCreateBodyDocumentOneEvidenceItemNoteMax = 10000

export const investigationsCreateBodyDocumentOneEvidenceMax = 12

export const investigationsCreateBodyDocumentOneNextEvidenceNumberExclusiveMin = 0

export const investigationsCreateBodyDocumentOneHypothesesItemIdMax = 128

export const investigationsCreateBodyDocumentOneHypothesesItemTitleMax = 500

export const investigationsCreateBodyDocumentOneHypothesesItemReasoningMax = 10000

export const investigationsCreateBodyDocumentOneHypothesesItemEvidenceIdsItemMax = 128

export const investigationsCreateBodyDocumentOneHypothesesItemEvidenceIdsMax = 12

export const investigationsCreateBodyDocumentOneHypothesesMax = 12

export const investigationsCreateBodyDocumentOneConclusionMax = 10000

export const investigationsCreateBodyDocumentOneDecisionMax = 10000

export const investigationsCreateBodyDocumentOneFollowUpMax = 2000

export const investigationsCreateBodyDocumentOneRunsItemIdMax = 128

export const investigationsCreateBodyDocumentOneRunsItemConclusionMax = 10000

export const investigationsCreateBodyDocumentOneRunsItemResultsItemEvidenceIdMax = 128

export const investigationsCreateBodyDocumentOneRunsItemResultsItemTitleMax = 200

export const investigationsCreateBodyDocumentOneRunsItemResultsItemSqlMax = 10000

export const investigationsCreateBodyDocumentOneRunsItemResultsItemColumnsItemMax = 500

export const investigationsCreateBodyDocumentOneRunsItemResultsItemColumnsMax = 20

export const investigationsCreateBodyDocumentOneRunsItemResultsItemRowsItemItemOneMax = 2000

export const investigationsCreateBodyDocumentOneRunsItemResultsItemRowsItemMax = 20

export const investigationsCreateBodyDocumentOneRunsItemResultsItemRowsMax = 50

export const investigationsCreateBodyDocumentOneRunsItemResultsItemErrorOneMax = 2000

export const investigationsCreateBodyDocumentOneRunsItemResultsMax = 12

export const investigationsCreateBodyDocumentOneRunsMax = 10

export const investigationsCreateBodyDocumentOneBaselineIdOneMax = 128

export const InvestigationsCreateBody = /* @__PURE__ */ zod.object({
    document: zod
        .object({
            version: zod.number(),
            question: zod.string().max(investigationsCreateBodyDocumentOneQuestionMax),
            status: zod.enum(['investigating', 'review', 'monitoring', 'closed']),
            context: zod.string().max(investigationsCreateBodyDocumentOneContextMax),
            checks: zod
                .array(zod.enum(['definition', 'maturity', 'tracking', 'population']))
                .max(investigationsCreateBodyDocumentOneChecksMax),
            evidence: zod
                .array(
                    zod.object({
                        id: zod.string().min(1).max(investigationsCreateBodyDocumentOneEvidenceItemIdMax),
                        reference: zod
                            .number()
                            .gt(investigationsCreateBodyDocumentOneEvidenceItemReferenceExclusiveMin),
                        title: zod.string().max(investigationsCreateBodyDocumentOneEvidenceItemTitleMax),
                        kind: zod.enum(['query', 'link']),
                        sql: zod.string().max(investigationsCreateBodyDocumentOneEvidenceItemSqlMax),
                        url: zod.string().max(investigationsCreateBodyDocumentOneEvidenceItemUrlMax),
                        note: zod.string().max(investigationsCreateBodyDocumentOneEvidenceItemNoteMax),
                    })
                )
                .max(investigationsCreateBodyDocumentOneEvidenceMax),
            nextEvidenceNumber: zod.number().gt(investigationsCreateBodyDocumentOneNextEvidenceNumberExclusiveMin),
            hypotheses: zod
                .array(
                    zod.object({
                        id: zod.string().min(1).max(investigationsCreateBodyDocumentOneHypothesesItemIdMax),
                        title: zod.string().max(investigationsCreateBodyDocumentOneHypothesesItemTitleMax),
                        status: zod.enum(['open', 'supported', 'ruled_out']),
                        reasoning: zod.string().max(investigationsCreateBodyDocumentOneHypothesesItemReasoningMax),
                        evidenceIds: zod
                            .array(
                                zod
                                    .string()
                                    .min(1)
                                    .max(investigationsCreateBodyDocumentOneHypothesesItemEvidenceIdsItemMax)
                            )
                            .max(investigationsCreateBodyDocumentOneHypothesesItemEvidenceIdsMax),
                    })
                )
                .max(investigationsCreateBodyDocumentOneHypothesesMax),
            conclusion: zod.string().max(investigationsCreateBodyDocumentOneConclusionMax),
            decision: zod.string().max(investigationsCreateBodyDocumentOneDecisionMax),
            followUp: zod.string().max(investigationsCreateBodyDocumentOneFollowUpMax),
            runs: zod
                .array(
                    zod.object({
                        id: zod.string().min(1).max(investigationsCreateBodyDocumentOneRunsItemIdMax),
                        at: zod.iso.datetime({ offset: true }),
                        conclusion: zod.string().max(investigationsCreateBodyDocumentOneRunsItemConclusionMax),
                        results: zod
                            .array(
                                zod.object({
                                    evidenceId: zod
                                        .string()
                                        .min(1)
                                        .max(investigationsCreateBodyDocumentOneRunsItemResultsItemEvidenceIdMax),
                                    title: zod
                                        .string()
                                        .max(investigationsCreateBodyDocumentOneRunsItemResultsItemTitleMax),
                                    sql: zod.string().max(investigationsCreateBodyDocumentOneRunsItemResultsItemSqlMax),
                                    columns: zod
                                        .array(
                                            zod
                                                .string()
                                                .max(
                                                    investigationsCreateBodyDocumentOneRunsItemResultsItemColumnsItemMax
                                                )
                                        )
                                        .max(investigationsCreateBodyDocumentOneRunsItemResultsItemColumnsMax),
                                    rows: zod
                                        .array(
                                            zod
                                                .array(
                                                    zod.union([
                                                        zod
                                                            .string()
                                                            .max(
                                                                investigationsCreateBodyDocumentOneRunsItemResultsItemRowsItemItemOneMax
                                                            ),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                )
                                                .max(investigationsCreateBodyDocumentOneRunsItemResultsItemRowsItemMax)
                                        )
                                        .max(investigationsCreateBodyDocumentOneRunsItemResultsItemRowsMax),
                                    truncated: zod.boolean(),
                                    error: zod.union([
                                        zod
                                            .string()
                                            .max(investigationsCreateBodyDocumentOneRunsItemResultsItemErrorOneMax),
                                        zod.null(),
                                    ]),
                                })
                            )
                            .max(investigationsCreateBodyDocumentOneRunsItemResultsMax),
                    })
                )
                .max(investigationsCreateBodyDocumentOneRunsMax),
            baselineId: zod.union([
                zod.string().min(1).max(investigationsCreateBodyDocumentOneBaselineIdOneMax),
                zod.null(),
            ]),
            example: zod.boolean(),
        })
        .describe('The investigation document to save. Version must be 1.'),
})

export const investigationsPartialUpdateBodyDocumentOneQuestionMax = 500

export const investigationsPartialUpdateBodyDocumentOneContextMax = 10000

export const investigationsPartialUpdateBodyDocumentOneChecksMax = 4

export const investigationsPartialUpdateBodyDocumentOneEvidenceItemIdMax = 128

export const investigationsPartialUpdateBodyDocumentOneEvidenceItemReferenceExclusiveMin = 0

export const investigationsPartialUpdateBodyDocumentOneEvidenceItemTitleMax = 200

export const investigationsPartialUpdateBodyDocumentOneEvidenceItemSqlMax = 10000

export const investigationsPartialUpdateBodyDocumentOneEvidenceItemUrlMax = 2000

export const investigationsPartialUpdateBodyDocumentOneEvidenceItemNoteMax = 10000

export const investigationsPartialUpdateBodyDocumentOneEvidenceMax = 12

export const investigationsPartialUpdateBodyDocumentOneNextEvidenceNumberExclusiveMin = 0

export const investigationsPartialUpdateBodyDocumentOneHypothesesItemIdMax = 128

export const investigationsPartialUpdateBodyDocumentOneHypothesesItemTitleMax = 500

export const investigationsPartialUpdateBodyDocumentOneHypothesesItemReasoningMax = 10000

export const investigationsPartialUpdateBodyDocumentOneHypothesesItemEvidenceIdsItemMax = 128

export const investigationsPartialUpdateBodyDocumentOneHypothesesItemEvidenceIdsMax = 12

export const investigationsPartialUpdateBodyDocumentOneHypothesesMax = 12

export const investigationsPartialUpdateBodyDocumentOneConclusionMax = 10000

export const investigationsPartialUpdateBodyDocumentOneDecisionMax = 10000

export const investigationsPartialUpdateBodyDocumentOneFollowUpMax = 2000

export const investigationsPartialUpdateBodyDocumentOneRunsItemIdMax = 128

export const investigationsPartialUpdateBodyDocumentOneRunsItemConclusionMax = 10000

export const investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemEvidenceIdMax = 128

export const investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemTitleMax = 200

export const investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemSqlMax = 10000

export const investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemColumnsItemMax = 500

export const investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemColumnsMax = 20

export const investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemRowsItemItemOneMax = 2000

export const investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemRowsItemMax = 20

export const investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemRowsMax = 50

export const investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemErrorOneMax = 2000

export const investigationsPartialUpdateBodyDocumentOneRunsItemResultsMax = 12

export const investigationsPartialUpdateBodyDocumentOneRunsMax = 10

export const investigationsPartialUpdateBodyDocumentOneBaselineIdOneMax = 128

export const investigationsPartialUpdateBodyDeletedDefault = false

export const InvestigationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    revision: zod.number().min(1).optional().describe('Last read revision. Stale writes are rejected with HTTP 409.'),
    document: zod
        .object({
            version: zod.number(),
            question: zod.string().max(investigationsPartialUpdateBodyDocumentOneQuestionMax),
            status: zod.enum(['investigating', 'review', 'monitoring', 'closed']),
            context: zod.string().max(investigationsPartialUpdateBodyDocumentOneContextMax),
            checks: zod
                .array(zod.enum(['definition', 'maturity', 'tracking', 'population']))
                .max(investigationsPartialUpdateBodyDocumentOneChecksMax),
            evidence: zod
                .array(
                    zod.object({
                        id: zod.string().min(1).max(investigationsPartialUpdateBodyDocumentOneEvidenceItemIdMax),
                        reference: zod
                            .number()
                            .gt(investigationsPartialUpdateBodyDocumentOneEvidenceItemReferenceExclusiveMin),
                        title: zod.string().max(investigationsPartialUpdateBodyDocumentOneEvidenceItemTitleMax),
                        kind: zod.enum(['query', 'link']),
                        sql: zod.string().max(investigationsPartialUpdateBodyDocumentOneEvidenceItemSqlMax),
                        url: zod.string().max(investigationsPartialUpdateBodyDocumentOneEvidenceItemUrlMax),
                        note: zod.string().max(investigationsPartialUpdateBodyDocumentOneEvidenceItemNoteMax),
                    })
                )
                .max(investigationsPartialUpdateBodyDocumentOneEvidenceMax),
            nextEvidenceNumber: zod
                .number()
                .gt(investigationsPartialUpdateBodyDocumentOneNextEvidenceNumberExclusiveMin),
            hypotheses: zod
                .array(
                    zod.object({
                        id: zod.string().min(1).max(investigationsPartialUpdateBodyDocumentOneHypothesesItemIdMax),
                        title: zod.string().max(investigationsPartialUpdateBodyDocumentOneHypothesesItemTitleMax),
                        status: zod.enum(['open', 'supported', 'ruled_out']),
                        reasoning: zod
                            .string()
                            .max(investigationsPartialUpdateBodyDocumentOneHypothesesItemReasoningMax),
                        evidenceIds: zod
                            .array(
                                zod
                                    .string()
                                    .min(1)
                                    .max(investigationsPartialUpdateBodyDocumentOneHypothesesItemEvidenceIdsItemMax)
                            )
                            .max(investigationsPartialUpdateBodyDocumentOneHypothesesItemEvidenceIdsMax),
                    })
                )
                .max(investigationsPartialUpdateBodyDocumentOneHypothesesMax),
            conclusion: zod.string().max(investigationsPartialUpdateBodyDocumentOneConclusionMax),
            decision: zod.string().max(investigationsPartialUpdateBodyDocumentOneDecisionMax),
            followUp: zod.string().max(investigationsPartialUpdateBodyDocumentOneFollowUpMax),
            runs: zod
                .array(
                    zod.object({
                        id: zod.string().min(1).max(investigationsPartialUpdateBodyDocumentOneRunsItemIdMax),
                        at: zod.iso.datetime({ offset: true }),
                        conclusion: zod.string().max(investigationsPartialUpdateBodyDocumentOneRunsItemConclusionMax),
                        results: zod
                            .array(
                                zod.object({
                                    evidenceId: zod
                                        .string()
                                        .min(1)
                                        .max(
                                            investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemEvidenceIdMax
                                        ),
                                    title: zod
                                        .string()
                                        .max(investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemTitleMax),
                                    sql: zod
                                        .string()
                                        .max(investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemSqlMax),
                                    columns: zod
                                        .array(
                                            zod
                                                .string()
                                                .max(
                                                    investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemColumnsItemMax
                                                )
                                        )
                                        .max(investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemColumnsMax),
                                    rows: zod
                                        .array(
                                            zod
                                                .array(
                                                    zod.union([
                                                        zod
                                                            .string()
                                                            .max(
                                                                investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemRowsItemItemOneMax
                                                            ),
                                                        zod.number(),
                                                        zod.boolean(),
                                                        zod.null(),
                                                    ])
                                                )
                                                .max(
                                                    investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemRowsItemMax
                                                )
                                        )
                                        .max(investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemRowsMax),
                                    truncated: zod.boolean(),
                                    error: zod.union([
                                        zod
                                            .string()
                                            .max(
                                                investigationsPartialUpdateBodyDocumentOneRunsItemResultsItemErrorOneMax
                                            ),
                                        zod.null(),
                                    ]),
                                })
                            )
                            .max(investigationsPartialUpdateBodyDocumentOneRunsItemResultsMax),
                    })
                )
                .max(investigationsPartialUpdateBodyDocumentOneRunsMax),
            baselineId: zod.union([
                zod.string().min(1).max(investigationsPartialUpdateBodyDocumentOneBaselineIdOneMax),
                zod.null(),
            ]),
            example: zod.boolean(),
        })
        .optional()
        .describe('Replacement document, preserving existing evidence and run IDs.'),
    deleted: zod
        .boolean()
        .default(investigationsPartialUpdateBodyDeletedDefault)
        .describe('Archive this investigation and remove it from the list.'),
})
