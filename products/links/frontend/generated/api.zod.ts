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
 * Create, read, update, and delete links.
 */
export const linksCreateBodyRedirectUrlMax = 2048

export const linksCreateBodyShortLinkDomainMax = 255

export const LinksCreateBody = /* @__PURE__ */ zod.object({
    redirect_url: zod.url().max(linksCreateBodyRedirectUrlMax),
    short_link_domain: zod
        .string()
        .max(linksCreateBodyShortLinkDomainMax)
        .describe('Domain where the short link is hosted, e.g. hog.gg'),
    short_code: zod.string(),
    description: zod.string().nullish(),
    _create_in_folder: zod.string().optional(),
})

/**
 * Create, read, update, and delete links.
 */
export const linksUpdateBodyRedirectUrlMax = 2048

export const linksUpdateBodyShortLinkDomainMax = 255

export const LinksUpdateBody = /* @__PURE__ */ zod.object({
    redirect_url: zod.url().max(linksUpdateBodyRedirectUrlMax),
    short_link_domain: zod
        .string()
        .max(linksUpdateBodyShortLinkDomainMax)
        .describe('Domain where the short link is hosted, e.g. hog.gg'),
    short_code: zod.string(),
    description: zod.string().nullish(),
    _create_in_folder: zod.string().optional(),
})

/**
 * Create, read, update, and delete links.
 */
export const linksPartialUpdateBodyRedirectUrlMax = 2048

export const linksPartialUpdateBodyShortLinkDomainMax = 255

export const LinksPartialUpdateBody = /* @__PURE__ */ zod.object({
    redirect_url: zod.url().max(linksPartialUpdateBodyRedirectUrlMax).optional(),
    short_link_domain: zod
        .string()
        .max(linksPartialUpdateBodyShortLinkDomainMax)
        .optional()
        .describe('Domain where the short link is hosted, e.g. hog.gg'),
    short_code: zod.string().optional(),
    description: zod.string().nullish(),
    _create_in_folder: zod.string().optional(),
})
