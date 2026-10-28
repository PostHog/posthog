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

export const knowledgeWriterMergePushesCreateBodyCommitShaRegExp = new RegExp('^[0-9a-f]{40}$')

export const KnowledgeWriterMergePushesCreateBody = /* @__PURE__ */ zod.object({
    commit_sha: zod
        .string()
        .regex(knowledgeWriterMergePushesCreateBodyCommitShaRegExp)
        .describe('The 40-character SHA of the master merge commit.'),
})
