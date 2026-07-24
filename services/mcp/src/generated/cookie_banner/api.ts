/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Manage the project's cookie banner. A project has at most one banner,
 * so list returns zero or one items and create fails once one exists.
 */
export const CookieBannerListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const CookieBannerListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Manage the project's cookie banner. A project has at most one banner,
 * so list returns zero or one items and create fails once one exists.
 */
export const CookieBannerCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const cookieBannerCreateBodyAppearanceOneTitleMax = 25

export const cookieBannerCreateBodyAppearanceOneDescriptionMax = 200

export const cookieBannerCreateBodyAppearanceOneAcceptButtonTextMax = 11

export const cookieBannerCreateBodyAppearanceOneDeclineButtonTextMax = 11

export const cookieBannerCreateBodyAppearanceOneBackgroundColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerCreateBodyAppearanceOneTextColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerCreateBodyAppearanceOneButtonColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerCreateBodyAppearanceOneButtonTextColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerCreateBodyAppearanceOnePreferencesButtonTextMax = 25

export const cookieBannerCreateBodyAppearanceOneTranslationsTitleMax = 25

export const cookieBannerCreateBodyAppearanceOneTranslationsDescriptionMax = 200

export const cookieBannerCreateBodyAppearanceOneTranslationsAcceptButtonTextMax = 11

export const cookieBannerCreateBodyAppearanceOneTranslationsDeclineButtonTextMax = 11

export const cookieBannerCreateBodyAppearanceOneTranslationsPreferencesButtonTextMax = 25

export const CookieBannerCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional().describe('Whether the banner is served to your website. Defaults to false.'),
    appearance: zod
        .object({
            title: zod
                .string()
                .max(cookieBannerCreateBodyAppearanceOneTitleMax)
                .optional()
                .describe("Banner headline. Plain text only. Defaults to 'We use cookies'."),
            description: zod
                .string()
                .max(cookieBannerCreateBodyAppearanceOneDescriptionMax)
                .optional()
                .describe('Body copy explaining what cookies are used for. Plain text only.'),
            acceptButtonText: zod
                .string()
                .max(cookieBannerCreateBodyAppearanceOneAcceptButtonTextMax)
                .optional()
                .describe("Label for the button that opts the visitor in to tracking. Defaults to 'Accept'."),
            declineButtonText: zod
                .string()
                .max(cookieBannerCreateBodyAppearanceOneDeclineButtonTextMax)
                .optional()
                .describe("Label for the button that opts the visitor out of tracking. Defaults to 'Decline'."),
            artStyle: zod
                .enum([
                    'none',
                    'posthog-logo',
                    'posthog-logomark-light',
                    'hedgehog-builder',
                    'hedgehog-business',
                    'hedgehog-hogzilla',
                    'hedgehog-robot',
                    'hedgehog-mobile',
                    'hedgehog-zen',
                    'hedgehog-lens',
                    'hedgehog-town-crier',
                    'hedgehog-wizard',
                    'hedgehog-legal',
                ])
                .describe(
                    '\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot\n\* `hedgehog-mobile` - hedgehog-mobile\n\* `hedgehog-zen` - hedgehog-zen\n\* `hedgehog-lens` - hedgehog-lens\n\* `hedgehog-town-crier` - hedgehog-town-crier\n\* `hedgehog-wizard` - hedgehog-wizard\n\* `hedgehog-legal` - hedgehog-legal'
                )
                .optional()
                .describe(
                    "Artwork shown on the banner: the PostHog logo, hedgehog art, or none. Defaults to 'posthog-logo'.\n\n\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot\n\* `hedgehog-mobile` - hedgehog-mobile\n\* `hedgehog-zen` - hedgehog-zen\n\* `hedgehog-lens` - hedgehog-lens\n\* `hedgehog-town-crier` - hedgehog-town-crier\n\* `hedgehog-wizard` - hedgehog-wizard\n\* `hedgehog-legal` - hedgehog-legal"
                ),
            position: zod
                .enum(['bottom-left', 'bottom-right', 'bottom-bar'])
                .describe(
                    '\* `bottom-left` - bottom-left\n\* `bottom-right` - bottom-right\n\* `bottom-bar` - bottom-bar'
                )
                .optional()
                .describe(
                    "Where the banner appears on the page. Defaults to 'bottom-right'.\n\n\* `bottom-left` - bottom-left\n\* `bottom-right` - bottom-right\n\* `bottom-bar` - bottom-bar"
                ),
            backgroundColor: zod
                .string()
                .regex(cookieBannerCreateBodyAppearanceOneBackgroundColorRegExp)
                .optional()
                .describe("Banner background color as a hex value. Defaults to '#eeefe9'."),
            textColor: zod
                .string()
                .regex(cookieBannerCreateBodyAppearanceOneTextColorRegExp)
                .optional()
                .describe("Banner text color as a hex value. Defaults to '#151515'."),
            buttonColor: zod
                .string()
                .regex(cookieBannerCreateBodyAppearanceOneButtonColorRegExp)
                .optional()
                .describe("Accept button background color as a hex value. Defaults to '#f54e00'."),
            buttonTextColor: zod
                .string()
                .regex(cookieBannerCreateBodyAppearanceOneButtonTextColorRegExp)
                .optional()
                .describe("Accept button text color as a hex value. Defaults to '#ffffff'."),
            whiteLabel: zod
                .boolean()
                .optional()
                .describe(
                    "Hide the 'Powered by PostHog' notice. Requires the white labelling entitlement on your plan."
                ),
            preferencesButtonText: zod
                .string()
                .max(cookieBannerCreateBodyAppearanceOnePreferencesButtonTextMax)
                .optional()
                .describe(
                    "Label for the link that opens the consent preferences panel. Defaults to 'Manage preferences'."
                ),
            showPreferences: zod
                .boolean()
                .optional()
                .describe(
                    "Show a 'Manage preferences' panel where visitors can consent to analytics and marketing cookies separately. Category choices are exposed to your site via the posthog:consent event. Defaults to false."
                ),
            cookielessFallback: zod
                .boolean()
                .optional()
                .describe(
                    'When a visitor declines analytics cookies, keep anonymous cookieless analytics (in-memory persistence, nothing stored on the device) instead of stopping tracking entirely. Defaults to false.'
                ),
            respectGpc: zod
                .boolean()
                .optional()
                .describe(
                    'Visitors broadcasting the Global Privacy Control signal are treated as declined and never shown the banner. An explicit choice made on your site still takes precedence. Defaults to true.'
                ),
            translations: zod
                .record(
                    zod.string(),
                    zod
                        .object({
                            title: zod
                                .string()
                                .max(cookieBannerCreateBodyAppearanceOneTranslationsTitleMax)
                                .optional()
                                .describe('Translated banner headline.'),
                            description: zod
                                .string()
                                .max(cookieBannerCreateBodyAppearanceOneTranslationsDescriptionMax)
                                .optional()
                                .describe('Translated body copy.'),
                            acceptButtonText: zod
                                .string()
                                .max(cookieBannerCreateBodyAppearanceOneTranslationsAcceptButtonTextMax)
                                .optional()
                                .describe('Translated accept button label.'),
                            declineButtonText: zod
                                .string()
                                .max(cookieBannerCreateBodyAppearanceOneTranslationsDeclineButtonTextMax)
                                .optional()
                                .describe('Translated decline button label.'),
                            preferencesButtonText: zod
                                .string()
                                .max(cookieBannerCreateBodyAppearanceOneTranslationsPreferencesButtonTextMax)
                                .optional()
                                .describe("Translated 'Manage preferences' label."),
                        })
                        .describe(
                            'Per-language overrides for the banner copy. Omitted keys fall back to the base\n(untranslated) copy for visitors matching this language.'
                        )
                )
                .optional()
                .describe(
                    "Per-language copy overrides keyed by ISO 639 language code (e.g. 'de', 'pt-BR'). The banner picks the visitor's browser language, falling back to the base copy."
                ),
        })
        .describe(
            'Appearance overrides for the banner. Omitted keys fall back to the PostHog-styled defaults\n(see products\/cookie_banner\/backend\/constants.py) when the banner is delivered.'
        )
        .optional()
        .describe('Appearance and copy overrides. Omitted keys use the PostHog-styled defaults.'),
})

/**
 * Manage the project's cookie banner. A project has at most one banner,
 * so list returns zero or one items and create fails once one exists.
 */
export const CookieBannerPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this cookie banner config.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const cookieBannerPartialUpdateBodyAppearanceOneTitleMax = 25

export const cookieBannerPartialUpdateBodyAppearanceOneDescriptionMax = 200

export const cookieBannerPartialUpdateBodyAppearanceOneAcceptButtonTextMax = 11

export const cookieBannerPartialUpdateBodyAppearanceOneDeclineButtonTextMax = 11

export const cookieBannerPartialUpdateBodyAppearanceOneBackgroundColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerPartialUpdateBodyAppearanceOneTextColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerPartialUpdateBodyAppearanceOneButtonColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerPartialUpdateBodyAppearanceOneButtonTextColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerPartialUpdateBodyAppearanceOnePreferencesButtonTextMax = 25

export const cookieBannerPartialUpdateBodyAppearanceOneTranslationsTitleMax = 25

export const cookieBannerPartialUpdateBodyAppearanceOneTranslationsDescriptionMax = 200

export const cookieBannerPartialUpdateBodyAppearanceOneTranslationsAcceptButtonTextMax = 11

export const cookieBannerPartialUpdateBodyAppearanceOneTranslationsDeclineButtonTextMax = 11

export const cookieBannerPartialUpdateBodyAppearanceOneTranslationsPreferencesButtonTextMax = 25

export const CookieBannerPartialUpdateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional().describe('Whether the banner is served to your website. Defaults to false.'),
    appearance: zod
        .object({
            title: zod
                .string()
                .max(cookieBannerPartialUpdateBodyAppearanceOneTitleMax)
                .optional()
                .describe("Banner headline. Plain text only. Defaults to 'We use cookies'."),
            description: zod
                .string()
                .max(cookieBannerPartialUpdateBodyAppearanceOneDescriptionMax)
                .optional()
                .describe('Body copy explaining what cookies are used for. Plain text only.'),
            acceptButtonText: zod
                .string()
                .max(cookieBannerPartialUpdateBodyAppearanceOneAcceptButtonTextMax)
                .optional()
                .describe("Label for the button that opts the visitor in to tracking. Defaults to 'Accept'."),
            declineButtonText: zod
                .string()
                .max(cookieBannerPartialUpdateBodyAppearanceOneDeclineButtonTextMax)
                .optional()
                .describe("Label for the button that opts the visitor out of tracking. Defaults to 'Decline'."),
            artStyle: zod
                .enum([
                    'none',
                    'posthog-logo',
                    'posthog-logomark-light',
                    'hedgehog-builder',
                    'hedgehog-business',
                    'hedgehog-hogzilla',
                    'hedgehog-robot',
                    'hedgehog-mobile',
                    'hedgehog-zen',
                    'hedgehog-lens',
                    'hedgehog-town-crier',
                    'hedgehog-wizard',
                    'hedgehog-legal',
                ])
                .describe(
                    '\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot\n\* `hedgehog-mobile` - hedgehog-mobile\n\* `hedgehog-zen` - hedgehog-zen\n\* `hedgehog-lens` - hedgehog-lens\n\* `hedgehog-town-crier` - hedgehog-town-crier\n\* `hedgehog-wizard` - hedgehog-wizard\n\* `hedgehog-legal` - hedgehog-legal'
                )
                .optional()
                .describe(
                    "Artwork shown on the banner: the PostHog logo, hedgehog art, or none. Defaults to 'posthog-logo'.\n\n\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot\n\* `hedgehog-mobile` - hedgehog-mobile\n\* `hedgehog-zen` - hedgehog-zen\n\* `hedgehog-lens` - hedgehog-lens\n\* `hedgehog-town-crier` - hedgehog-town-crier\n\* `hedgehog-wizard` - hedgehog-wizard\n\* `hedgehog-legal` - hedgehog-legal"
                ),
            position: zod
                .enum(['bottom-left', 'bottom-right', 'bottom-bar'])
                .describe(
                    '\* `bottom-left` - bottom-left\n\* `bottom-right` - bottom-right\n\* `bottom-bar` - bottom-bar'
                )
                .optional()
                .describe(
                    "Where the banner appears on the page. Defaults to 'bottom-right'.\n\n\* `bottom-left` - bottom-left\n\* `bottom-right` - bottom-right\n\* `bottom-bar` - bottom-bar"
                ),
            backgroundColor: zod
                .string()
                .regex(cookieBannerPartialUpdateBodyAppearanceOneBackgroundColorRegExp)
                .optional()
                .describe("Banner background color as a hex value. Defaults to '#eeefe9'."),
            textColor: zod
                .string()
                .regex(cookieBannerPartialUpdateBodyAppearanceOneTextColorRegExp)
                .optional()
                .describe("Banner text color as a hex value. Defaults to '#151515'."),
            buttonColor: zod
                .string()
                .regex(cookieBannerPartialUpdateBodyAppearanceOneButtonColorRegExp)
                .optional()
                .describe("Accept button background color as a hex value. Defaults to '#f54e00'."),
            buttonTextColor: zod
                .string()
                .regex(cookieBannerPartialUpdateBodyAppearanceOneButtonTextColorRegExp)
                .optional()
                .describe("Accept button text color as a hex value. Defaults to '#ffffff'."),
            whiteLabel: zod
                .boolean()
                .optional()
                .describe(
                    "Hide the 'Powered by PostHog' notice. Requires the white labelling entitlement on your plan."
                ),
            preferencesButtonText: zod
                .string()
                .max(cookieBannerPartialUpdateBodyAppearanceOnePreferencesButtonTextMax)
                .optional()
                .describe(
                    "Label for the link that opens the consent preferences panel. Defaults to 'Manage preferences'."
                ),
            showPreferences: zod
                .boolean()
                .optional()
                .describe(
                    "Show a 'Manage preferences' panel where visitors can consent to analytics and marketing cookies separately. Category choices are exposed to your site via the posthog:consent event. Defaults to false."
                ),
            cookielessFallback: zod
                .boolean()
                .optional()
                .describe(
                    'When a visitor declines analytics cookies, keep anonymous cookieless analytics (in-memory persistence, nothing stored on the device) instead of stopping tracking entirely. Defaults to false.'
                ),
            respectGpc: zod
                .boolean()
                .optional()
                .describe(
                    'Visitors broadcasting the Global Privacy Control signal are treated as declined and never shown the banner. An explicit choice made on your site still takes precedence. Defaults to true.'
                ),
            translations: zod
                .record(
                    zod.string(),
                    zod
                        .object({
                            title: zod
                                .string()
                                .max(cookieBannerPartialUpdateBodyAppearanceOneTranslationsTitleMax)
                                .optional()
                                .describe('Translated banner headline.'),
                            description: zod
                                .string()
                                .max(cookieBannerPartialUpdateBodyAppearanceOneTranslationsDescriptionMax)
                                .optional()
                                .describe('Translated body copy.'),
                            acceptButtonText: zod
                                .string()
                                .max(cookieBannerPartialUpdateBodyAppearanceOneTranslationsAcceptButtonTextMax)
                                .optional()
                                .describe('Translated accept button label.'),
                            declineButtonText: zod
                                .string()
                                .max(cookieBannerPartialUpdateBodyAppearanceOneTranslationsDeclineButtonTextMax)
                                .optional()
                                .describe('Translated decline button label.'),
                            preferencesButtonText: zod
                                .string()
                                .max(cookieBannerPartialUpdateBodyAppearanceOneTranslationsPreferencesButtonTextMax)
                                .optional()
                                .describe("Translated 'Manage preferences' label."),
                        })
                        .describe(
                            'Per-language overrides for the banner copy. Omitted keys fall back to the base\n(untranslated) copy for visitors matching this language.'
                        )
                )
                .optional()
                .describe(
                    "Per-language copy overrides keyed by ISO 639 language code (e.g. 'de', 'pt-BR'). The banner picks the visitor's browser language, falling back to the base copy."
                ),
        })
        .describe(
            'Appearance overrides for the banner. Omitted keys fall back to the PostHog-styled defaults\n(see products\/cookie_banner\/backend\/constants.py) when the banner is delivered.'
        )
        .optional()
        .describe('Appearance and copy overrides. Omitted keys use the PostHog-styled defaults.'),
})
