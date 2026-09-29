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

export const linksCreateBodyShortCodeMax = 255

export const LinksCreateBody = /* @__PURE__ */ zod.object({
    redirect_url: zod.url().max(linksCreateBodyRedirectUrlMax).describe('Destination the short link redirects to.'),
    short_link_domain: zod
        .string()
        .max(linksCreateBodyShortLinkDomainMax)
        .describe('Domain the short link is hosted on. Only phog.gg is accepted.'),
    short_code: zod
        .string()
        .max(linksCreateBodyShortCodeMax)
        .describe("The unique code\/path that identifies the short link, e.g. 'abc123'"),
    description: zod.string().nullish().describe('Free-form note about what the link is for.'),
    _create_in_folder: zod.string().optional().describe('Folder path to file the link under in the project tree.'),
})

/**
 * Create, read, update, and delete links.
 */
export const linksUpdateBodyRedirectUrlMax = 2048

export const linksUpdateBodyShortLinkDomainMax = 255

export const linksUpdateBodyShortCodeMax = 255

export const LinksUpdateBody = /* @__PURE__ */ zod.object({
    redirect_url: zod.url().max(linksUpdateBodyRedirectUrlMax).describe('Destination the short link redirects to.'),
    short_link_domain: zod
        .string()
        .max(linksUpdateBodyShortLinkDomainMax)
        .describe('Domain the short link is hosted on. Only phog.gg is accepted.'),
    short_code: zod
        .string()
        .max(linksUpdateBodyShortCodeMax)
        .describe("The unique code\/path that identifies the short link, e.g. 'abc123'"),
    description: zod.string().nullish().describe('Free-form note about what the link is for.'),
    _create_in_folder: zod.string().optional().describe('Folder path to file the link under in the project tree.'),
})

/**
 * Create, read, update, and delete links.
 */
export const linksPartialUpdateBodyRedirectUrlMax = 2048

export const linksPartialUpdateBodyShortLinkDomainMax = 255

export const linksPartialUpdateBodyShortCodeMax = 255

export const LinksPartialUpdateBody = /* @__PURE__ */ zod.object({
    redirect_url: zod
        .url()
        .max(linksPartialUpdateBodyRedirectUrlMax)
        .optional()
        .describe('Destination the short link redirects to.'),
    short_link_domain: zod
        .string()
        .max(linksPartialUpdateBodyShortLinkDomainMax)
        .optional()
        .describe('Domain the short link is hosted on. Only phog.gg is accepted.'),
    short_code: zod
        .string()
        .max(linksPartialUpdateBodyShortCodeMax)
        .optional()
        .describe("The unique code\/path that identifies the short link, e.g. 'abc123'"),
    description: zod.string().nullish().describe('Free-form note about what the link is for.'),
    _create_in_folder: zod.string().optional().describe('Folder path to file the link under in the project tree.'),
})
