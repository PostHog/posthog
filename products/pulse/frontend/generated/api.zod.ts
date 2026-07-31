/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { BriefConfigApi, GenerateBriefRequestApi, PatchedBriefConfigApi } from './api.zod.schemas'

export const PulseBriefConfigsCreateBody = BriefConfigApi

export const PulseBriefConfigsUpdateBody = BriefConfigApi

export const PulseBriefConfigsPartialUpdateBody = PatchedBriefConfigApi

export const PulseBriefsGenerateCreateBody = GenerateBriefRequestApi
