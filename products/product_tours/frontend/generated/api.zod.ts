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
    GenerateRequestApi,
    PatchedProductTourSerializerCreateUpdateOnlyApi,
    ProductTourApi,
    ProductTourSerializerCreateUpdateOnlyApi,
} from './api.zod.schemas'

/**
 * Create, read, update, and manage product tours and their targeting.
 */
export const ProductToursCreateBody = ProductTourSerializerCreateUpdateOnlyApi

/**
 * Create, read, update, and manage product tours and their targeting.
 */
export const ProductToursUpdateBody = ProductTourApi

/**
 * Create, read, update, and manage product tours and their targeting.
 */
export const ProductToursPartialUpdateBody = PatchedProductTourSerializerCreateUpdateOnlyApi

/**
 * Save draft content (server-side merge). No side effects triggered.
 */
export const ProductToursDraftPartialUpdateBody = PatchedProductTourSerializerCreateUpdateOnlyApi

/**
 * Generate tour step content using AI.
 */
export const ProductToursGenerateCreateBody = GenerateRequestApi

/**
 * Commit draft to live tour. Runs full validation and triggers side effects.
 *
 * Accepts an optional body payload. If provided, merges it into the draft
 * before publishing so the caller can save + publish in a single request.
 */
export const ProductToursPublishDraftCreateBody = ProductTourSerializerCreateUpdateOnlyApi
