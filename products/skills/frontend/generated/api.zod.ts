/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    LLMSkillCreateApi,
    LLMSkillDuplicateApi,
    LLMSkillFileCreateApi,
    LLMSkillFileRenameApi,
    LLMSkillImportApi,
    LLMSkillMarketplaceIssueApi,
    PatchedLLMSkillPublishApi,
} from './api.zod.schemas'

export const LlmSkillsCreateBody = LLMSkillCreateApi

export const LlmSkillsImportCreateBody = LLMSkillImportApi

/**
 * Mint the user's read-only marketplace credential (or rotate it) and return the install command.
 *
 * Per-user: rotating only ever invalidates this user's own credential, never a teammate's.
 */
export const LlmSkillsMarketplaceInstallCommandCreateBody = LLMSkillMarketplaceIssueApi

export const LlmSkillsNamePartialUpdateBody = PatchedLLMSkillPublishApi

export const LlmSkillsNameDuplicateCreateBody = LLMSkillDuplicateApi

export const LlmSkillsNameFilesCreateBody = LLMSkillFileCreateApi

export const LlmSkillsNameFilesRenameCreateBody = LLMSkillFileRenameApi
