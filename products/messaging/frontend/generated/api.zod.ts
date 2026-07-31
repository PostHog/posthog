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
    AddOptOutRequestApi,
    AddSuppressionRequestApi,
    MessageCategoryApi,
    MessageTemplateApi,
    PatchedDesignPatchApi,
    PatchedMessageCategoryApi,
    PatchedMessageTemplateApi,
} from './api.zod.schemas'

export const MessagingCategoriesCreateBody = MessageCategoryApi

export const MessagingCategoriesUpdateBody = MessageCategoryApi

export const MessagingCategoriesPartialUpdateBody = PatchedMessageCategoryApi

/**
 * Import subscription topics and globally unsubscribed users from Customer.io API.
 * Persists the App API key in Integration(kind="customerio-app").
 * If no app_api_key is provided, reuses the stored Integration key.
 */
export const MessagingCategoriesImportFromCustomerioCreateBody = MessageCategoryApi

/**
 * Import customer preferences from CSV file
 * Expected CSV columns: id, email, cio_subscription_preferences
 */
export const MessagingCategoriesImportPreferencesCsvCreateBody = MessageCategoryApi

/**
 * Save Customer.io Track API credentials and/or toggle outbound sync.
 *
 * Accepts:
 *   - site_id (optional): set on first creation only
 *   - api_key (optional): set on first creation only
 *   - region (optional): "us" or "eu", set on first creation only
 *   - track_enabled (required): enable or disable outbound sync
 */
export const MessagingCategoriesSaveTrackConfigCreateBody = MessageCategoryApi

/**
 * Save webhook signing secret and/or toggle the Customer.io webhook sync.
 *
 * Accepts:
 *   - webhook_signing_secret (optional): set on first creation only
 *   - webhook_enabled (required): enable or disable the webhook
 */
export const MessagingCategoriesSaveWebhookConfigCreateBody = MessageCategoryApi

/**
 * Manually add a recipient to the opt-out list for a specific category or all marketing messages.
 * @summary Manually add a recipient to the opt-out list
 */
export const MessagingPreferencesAddOptOutCreateBody = AddOptOutRequestApi

/**
 * Manually suppress an email address so no workflow sends to it.
 * @summary Manually add an email address to the suppression list
 */
export const MessagingSuppressionsAddSuppressionCreateBody = AddSuppressionRequestApi

/**
 * Remove an address from the suppression list so it can receive messages again.
 * @summary Remove an email address from the suppression list
 */
export const MessagingSuppressionsRemoveSuppressionCreateBody = AddSuppressionRequestApi

export const MessagingTemplatesCreateBody = MessageTemplateApi

export const MessagingTemplatesUpdateBody = MessageTemplateApi

export const MessagingTemplatesPartialUpdateBody = PatchedMessageTemplateApi

export const MessagingTemplatesDesignPartialUpdateBody = PatchedDesignPatchApi
