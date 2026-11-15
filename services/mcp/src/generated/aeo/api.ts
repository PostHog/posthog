/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 31 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Lists the project's brand catalog by domain: the project itself, competitors, publishers and domains nobody has labeled yet. Each daily run adds the domains its answers cited for the first time.
 * @summary List AEO brands
 */
export const AeoBrandsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoBrandsListQueryLimitMax = 1000

export const aeoBrandsListQuerySearchMax = 200

export const AeoBrandsListQueryParams = () => zod.object({
    kind: zod
        .enum(['own', 'competitor', 'publisher', 'unknown'])
        .optional()
        .describe(
            'Only list brands of this kind.\n\n\* `own` - Own\n\* `competitor` - Competitor\n\* `publisher` - Publisher\n\* `unknown` - Unknown'
        ),
    limit: zod.number().max(aeoBrandsListQueryLimitMax).optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod
        .string()
        .max(aeoBrandsListQuerySearchMax)
        .optional()
        .describe('Only list brands whose domain or name contains this text, ignoring case.'),
    status: zod
        .enum(['suggested', 'confirmed', 'ignored'])
        .optional()
        .describe(
            'Only list brands with this review status.\n\n\* `suggested` - Suggested\n\* `confirmed` - Confirmed\n\* `ignored` - Ignored'
        ),
})

/**
 * Adds a brand to the project's brand catalog by domain, confirmed. Add the project's own site with kind 'own' before the first daily run: only own brands count as the project in citations and mentions, and the run skips a project without one. Returns 400 when the catalog already has the domain; update that brand instead.
 * @summary Add an AEO brand
 */
export const AeoBrandsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoBrandsCreateBodyDomainMax = 253

export const aeoBrandsCreateBodyNameMax = 200

export const aeoBrandsCreateBodyAliasesItemMax = 200

export const aeoBrandsCreateBodyAliasesMax = 20

export const AeoBrandsCreateBody = () => zod.object({
    domain: zod
        .string()
        .max(aeoBrandsCreateBodyDomainMax)
        .describe(
            "The brand's domain or a URL on it, for example 'example.com'. Stored as its registrable domain, so citations on its subdomains count for the brand."
        ),
    name: zod
        .string()
        .max(aeoBrandsCreateBodyNameMax)
        .optional()
        .describe('Brand name as people say it. Guessed from the domain when empty.'),
    kind: zod
        .enum(['own', 'competitor', 'publisher', 'unknown'])
        .describe('\* `own` - Own\n\* `competitor` - Competitor\n\* `publisher` - Publisher\n\* `unknown` - Unknown')
        .describe(
            "What the brand is to the project: 'own' (the project's site, counted as us in citations), 'competitor', 'publisher' or 'unknown'.\n\n\* `own` - Own\n\* `competitor` - Competitor\n\* `publisher` - Publisher\n\* `unknown` - Unknown"
        ),
    aliases: zod
        .array(zod.string().max(aeoBrandsCreateBodyAliasesItemMax).describe('One other name for the brand.'))
        .max(aeoBrandsCreateBodyAliasesMax)
        .optional()
        .describe(
            'Other names for the brand, used to find it in answer text. Names are trimmed, and repeated names are dropped.'
        ),
})

/**
 * Gets one brand from the project's brand catalog.
 * @summary Get an AEO brand
 */
export const AeoBrandsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Renames, relabels, confirms or ignores a brand, or replaces its other names. The daily run keeps these edits; it only adds newly cited domains.
 * @summary Update an AEO brand
 */
export const AeoBrandsPartialUpdateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoBrandsPartialUpdateBodyNameMax = 200

export const aeoBrandsPartialUpdateBodyAliasesItemMax = 200

export const aeoBrandsPartialUpdateBodyAliasesMax = 20

export const AeoBrandsPartialUpdateBody = () => zod.object({
    name: zod.string().max(aeoBrandsPartialUpdateBodyNameMax).optional().describe('Brand name as people say it.'),
    kind: zod
        .enum(['own', 'competitor', 'publisher', 'unknown'])
        .describe('\* `own` - Own\n\* `competitor` - Competitor\n\* `publisher` - Publisher\n\* `unknown` - Unknown')
        .optional()
        .describe(
            "What the brand is to the project: 'own', 'competitor', 'publisher' or 'unknown'.\n\n\* `own` - Own\n\* `competitor` - Competitor\n\* `publisher` - Publisher\n\* `unknown` - Unknown"
        ),
    status: zod
        .enum(['suggested', 'confirmed', 'ignored'])
        .describe('\* `suggested` - Suggested\n\* `confirmed` - Confirmed\n\* `ignored` - Ignored')
        .optional()
        .describe(
            "'confirmed' to accept the brand, 'ignored' to hide it, 'suggested' to put it back for review.\n\n\* `suggested` - Suggested\n\* `confirmed` - Confirmed\n\* `ignored` - Ignored"
        ),
    aliases: zod
        .array(zod.string().max(aeoBrandsPartialUpdateBodyAliasesItemMax).describe('One other name for the brand.'))
        .max(aeoBrandsPartialUpdateBodyAliasesMax)
        .optional()
        .describe("Replaces the brand's other names. Names are trimmed, and repeated names are dropped."),
})

/**
 * Lists every answer engine the product can run, in display order, with whether the project runs it and how often. The no-search engines answer from training data alone and start off.
 * @summary List AEO answer engines
 */
export const AeoEnginesListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Turns an answer engine on or off for the project, or sets how often it checks each prompt. The next daily run uses the change. Each check on an engine is a paid model call.
 * @summary Update an AEO answer engine
 */
export const AeoEnginesPartialUpdateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const AeoEnginesPartialUpdateBody = () => zod.object({
    enabled: zod.boolean().optional().describe("Whether the daily run checks the project's prompts on this engine."),
    frequency: zod
        .enum(['daily', 'weekly'])
        .describe('\* `daily` - Daily\n\* `weekly` - Weekly')
        .optional()
        .describe(
            "'daily' or 'weekly'. Weekly checks each prompt once a week and costs a seventh as much.\n\n\* `daily` - Daily\n\* `weekly` - Weekly"
        ),
})

/**
 * Lists the project's keyword list, by keyword. The list holds at most 200 keywords, so it is never paged.
 * @summary List AEO keywords
 */
export const AeoKeywordsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Adds keywords to the project's keyword list. Send many at once. Blank entries and keywords already in the list are skipped and counted. Fails with 400 when the new keywords would take the list past 200.
 * @summary Add AEO keywords
 */
export const AeoKeywordsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoKeywordsCreateBodyKeywordsItemMax = 200

export const aeoKeywordsCreateBodyKeywordsMax = 200

export const AeoKeywordsCreateBody = () => zod.object({
    keywords: zod
        .array(
            zod
                .string()
                .max(aeoKeywordsCreateBodyKeywordsItemMax)
                .describe('One keyword or phrase, at most 100 characters once whitespace is collapsed.')
        )
        .min(1)
        .max(aeoKeywordsCreateBodyKeywordsMax)
        .describe(
            'Keywords to add. Each is lowercased and its whitespace collapsed. Blank entries, entries longer than 100 characters, and keywords the project already tracks are skipped. A project tracks at most 200 keywords.'
        ),
})

/**
 * Gets one keyword from the project's keyword list.
 * @summary Get an AEO keyword
 */
export const AeoKeywordsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Removes a keyword from the project's keyword list. Checks are not changed, so adding it back restores its report.
 * @summary Remove an AEO keyword
 */
export const AeoKeywordsDestroyParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Gets the words and two-word phrases the engines added to their web searches beyond the prompt over the last 'days' days (default 7), such as years, 'pricing', 'vs' or 'site:'. They show the content the engines look for. Each modifier has a kind, how many answers used it, the citation rate in those answers against the baseline, the engines that used it and example searches. Pass 'keyword' to only count answers whose searches contain it, and 'branded', 'engine' or 'topic' to count only the answers to branded or non-branded prompts, of one answer engine, or of one topic.
 * @summary Get AEO search modifiers
 */
export const AeoKeywordsModifiersParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoKeywordsModifiersQueryBrandedDefault = `all`
export const aeoKeywordsModifiersQueryDaysDefault = 7
export const aeoKeywordsModifiersQueryDaysMax = 90

export const aeoKeywordsModifiersQueryEngineMax = 64

export const aeoKeywordsModifiersQueryKeywordMax = 100

export const aeoKeywordsModifiersQueryTopicMax = 200

export const AeoKeywordsModifiersQueryParams = () => zod.object({
    branded: zod
        .enum(['all', 'branded', 'non_branded'])
        .default(aeoKeywordsModifiersQueryBrandedDefault)
        .describe(
            "Which answers to count, by the prompt as it ran: 'all' (default), 'branded' (the prompt names the brand) or 'non_branded'. A prompt is branded when its text names the brand: the registrable name of a target domain as a word, case ignored, so 'example' and 'example.com' both name example.com. Branded prompts almost always get answers that mention the brand.\n\n\* `all` - All\n\* `branded` - Branded\n\* `non_branded` - Non-branded"
        ),
    days: zod
        .number()
        .min(1)
        .max(aeoKeywordsModifiersQueryDaysMax)
        .default(aeoKeywordsModifiersQueryDaysDefault)
        .describe("Length of the window in days, ending today in the project's timezone. Default 7, at most 90."),
    engine: zod
        .string()
        .max(aeoKeywordsModifiersQueryEngineMax)
        .nullish()
        .describe(
            "Only count checks from this answer engine, for example 'claude-web-search'. Omit to count every engine."
        ),
    keyword: zod
        .string()
        .min(1)
        .max(aeoKeywordsModifiersQueryKeywordMax)
        .optional()
        .describe(
            "Only count answers whose web searches contain this phrase, case ignored. Usually one of the project's keywords."
        ),
    topic: zod
        .string()
        .max(aeoKeywordsModifiersQueryTopicMax)
        .nullish()
        .describe(
            'Only count checks that ran with this prompt topic. A prompt moved to another topic keeps its past checks under the old one. An empty value counts the checks of prompts that had no topic. Omit to count every topic.'
        ),
})

/**
 * Gets one row per keyword for the last 'days' days (default 7) in the project's timezone: how many prompts contain it and how those answers mention and cite the project, how often the engines searched for it and the citation rate in those answers, and how often answers use it, with the brand-mention rate, citation position and how early the brand is named in those answers. All rates are over answered checks. A keyword matches as a phrase, case ignored. Pass 'branded', 'engine' or 'topic' to count only the answers to branded or non-branded prompts, of one answer engine, or of one topic.
 * @summary Get the AEO keyword report
 */
export const AeoKeywordsReportParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoKeywordsReportQueryBrandedDefault = `all`
export const aeoKeywordsReportQueryDaysDefault = 7
export const aeoKeywordsReportQueryDaysMax = 90

export const aeoKeywordsReportQueryEngineMax = 64

export const aeoKeywordsReportQueryTopicMax = 200

export const AeoKeywordsReportQueryParams = () => zod.object({
    branded: zod
        .enum(['all', 'branded', 'non_branded'])
        .default(aeoKeywordsReportQueryBrandedDefault)
        .describe(
            "Which answers to count, by the prompt as it ran: 'all' (default), 'branded' (the prompt names the brand) or 'non_branded'. A prompt is branded when its text names the brand: the registrable name of a target domain as a word, case ignored, so 'example' and 'example.com' both name example.com. Branded prompts almost always get answers that mention the brand.\n\n\* `all` - All\n\* `branded` - Branded\n\* `non_branded` - Non-branded"
        ),
    days: zod
        .number()
        .min(1)
        .max(aeoKeywordsReportQueryDaysMax)
        .default(aeoKeywordsReportQueryDaysDefault)
        .describe("Length of the window in days, ending today in the project's timezone. Default 7, at most 90."),
    engine: zod
        .string()
        .max(aeoKeywordsReportQueryEngineMax)
        .nullish()
        .describe(
            "Only count checks from this answer engine, for example 'claude-web-search'. Omit to count every engine."
        ),
    topic: zod
        .string()
        .max(aeoKeywordsReportQueryTopicMax)
        .nullish()
        .describe(
            'Only count checks that ran with this prompt topic. A prompt moved to another topic keeps its past checks under the old one. An empty value counts the checks of prompts that had no topic. Omit to count every topic.'
        ),
})

/**
 * Suggests keywords to add to the project's keyword list. Requires AI data processing approved for the organization. PostHog ranks keywords from the site, the project's tracked prompts and topics, and the web searches the engines ran while answering them, and gives a reason for each. PostHog has no search-volume data: each suggestion only carries how many recent answers searched for it. Nothing is saved: add the keywords you keep with aeo_keywords create. Keywords already in the list and keywords that name the brand are left out. Fails with 400 when the list already holds 200 keywords. Returns a pending job right away; poll GET aeo_keywords/suggest/<id>/ until it completes, which takes up to a few minutes.
 * @summary Suggest AEO keywords
 */
export const AeoKeywordsSuggestParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoKeywordsSuggestBodyDomainMax = 200

export const aeoKeywordsSuggestBodyBrandMax = 200

export const aeoKeywordsSuggestBodyDescriptionMax = 1000

export const aeoKeywordsSuggestBodyCountDefault = 20
export const aeoKeywordsSuggestBodyCountMax = 50

export const AeoKeywordsSuggestBody = () => zod.object({
    domain: zod
        .string()
        .max(aeoKeywordsSuggestBodyDomainMax)
        .describe(
            "The project's site, for example posthog.com. The model reads it with web search when the project's prompts and searches are not enough."
        ),
    brand: zod
        .string()
        .max(aeoKeywordsSuggestBodyBrandMax)
        .optional()
        .describe('The brand name. Inferred from the site when empty. Keywords that name the brand are left out.'),
    description: zod
        .string()
        .max(aeoKeywordsSuggestBodyDescriptionMax)
        .optional()
        .describe('What the product does and who it is for. Inferred from the site when empty.'),
    count: zod
        .number()
        .min(1)
        .max(aeoKeywordsSuggestBodyCountMax)
        .default(aeoKeywordsSuggestBodyCountDefault)
        .describe(
            'How many keywords to suggest, at most 50, and never more than the room left in the 200-keyword list.'
        ),
})

/**
 * Gets a keyword suggestion job started with POST aeo_keywords/suggest/. status is pending while PostHog works, then completed with the suggestions or failed with an error. Jobs expire an hour after their last update.
 * @summary Get AEO keyword suggestions
 */
export const aeoKeywordsSuggestionRetrievePathJobIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const AeoKeywordsSuggestionRetrieveParams = () => zod.object({
    job_id: zod.string().regex(aeoKeywordsSuggestionRetrievePathJobIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Lists the project's AEO prompt set, ordered by topic and then rank, one page at a time. Filter by topic, by on/off state, by whether the prompt names the brand, or to the prompts that need improvement, optionally over 'days' days and one 'engine'. Archived prompts are left out unless include_archived is true. Each prompt carries its latest check per answer engine.
 * @summary List AEO prompts
 */
export const AeoPromptsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoPromptsListQueryDaysDefault = 30
export const aeoPromptsListQueryDaysMax = 90

export const aeoPromptsListQueryEngineMax = 64

export const aeoPromptsListQueryIncludeArchivedDefault = false
export const aeoPromptsListQueryLimitMax = 1000

export const aeoPromptsListQueryNeedsImprovementDefault = false
export const aeoPromptsListQueryTopicMax = 200

export const AeoPromptsListQueryParams = () => zod.object({
    active: zod.boolean().nullish().describe('Only list prompts that are on (true) or off (false). Omit to list both.'),
    branded: zod
        .boolean()
        .nullish()
        .describe(
            "Only list prompts whose current text names the brand (true) or does not (false). Omit to list both. A prompt is branded when its text names the brand: the registrable name of a target domain as a word, case ignored, so 'example' and 'example.com' both name example.com. Branded prompts almost always get answers that mention the brand."
        ),
    days: zod
        .number()
        .min(1)
        .max(aeoPromptsListQueryDaysMax)
        .default(aeoPromptsListQueryDaysDefault)
        .describe(
            'The window needs_improvement reads, in days ending now. Default 30, at most 90. Ignored unless needs_improvement is true.'
        ),
    engine: zod
        .string()
        .max(aeoPromptsListQueryEngineMax)
        .nullish()
        .describe(
            "With needs_improvement, only read the answers of this engine, for example 'claude-web-search'. Ignored unless needs_improvement is true."
        ),
    include_archived: zod
        .boolean()
        .default(aeoPromptsListQueryIncludeArchivedDefault)
        .describe('Also list archived prompts. Archived prompts are left out by default.'),
    limit: zod.number().max(aeoPromptsListQueryLimitMax).optional().describe('Number of results to return per page.'),
    needs_improvement: zod
        .boolean()
        .default(aeoPromptsListQueryNeedsImprovementDefault)
        .describe(
            "Only list prompts that the engines answered in the last 'days' days without citing a target domain. Prompts with no answered check in that window are left out."
        ),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    topic: zod
        .string()
        .max(aeoPromptsListQueryTopicMax)
        .optional()
        .describe('Only list prompts with this topic. An empty value lists the prompts that have no topic.'),
})

/**
 * Gets one prompt from the project's AEO prompt set, archived ones included, with its latest check per answer engine.
 * @summary Get an AEO prompt
 */
export const AeoPromptsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Turns a prompt on or off, changes its topic, archives or restores it, or changes its text. A text change adds the next version and makes it current, and current_version moves back to an earlier one. The prompt keeps its id, and past checks are always kept.
 * @summary Update an AEO prompt
 */
export const AeoPromptsPartialUpdateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoPromptsPartialUpdateBodyTopicMax = 200

export const aeoPromptsPartialUpdateBodyPromptMax = 2000

export const aeoPromptsPartialUpdateBodyVersionDescriptionMax = 400

export const AeoPromptsPartialUpdateBody = () => zod.object({
    active: zod.boolean().nullish().describe('Turn the prompt on or off for future runs.'),
    topic: zod
        .string()
        .max(aeoPromptsPartialUpdateBodyTopicMax)
        .optional()
        .describe(
            'New topic for the prompt. An empty string removes the topic. Past checks keep the topic they ran with.'
        ),
    prompt: zod
        .string()
        .max(aeoPromptsPartialUpdateBodyPromptMax)
        .optional()
        .describe(
            'New text for the prompt. A change adds the next version and makes it current; the prompt keeps its id and its check history, and each check records the version that ran. A change of case or whitespace only adds no version. Fails with 409 when another prompt in the set already has the text.'
        ),
    version_description: zod
        .string()
        .max(aeoPromptsPartialUpdateBodyVersionDescriptionMax)
        .optional()
        .describe("Optional note on what the text change does, stored on the new version. Send it with 'prompt'."),
    current_version: zod
        .number()
        .min(1)
        .nullish()
        .describe(
            'Make an existing version current again, for example to roll back a text change. Adds no version. Fails with 400 when the version does not exist, and with 409 when another prompt has its text.'
        ),
    archived: zod
        .boolean()
        .nullish()
        .describe(
            "True archives the prompt: it is turned off, never runs again, and keeps its check history. Send it without other fields. False restores an archived prompt. A restored prompt stays off unless 'active' is true in the same request. An archived prompt accepts no other change until it is restored."
        ),
})

/**
 * Archives a prompt: it is turned off and never runs again. Nothing is deleted, and its versions and checks are kept. Restore it with a PATCH of archived=false.
 * @summary Archive an AEO prompt
 */
export const AeoPromptsDestroyParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Lists every check of one prompt, newest first, one page at a time. Filter by engine, by prompt version, or with since to see only checks from a point in time on. Each check has the engine's answer, the URLs it cited, the searches it ran and the prompt version it ran. Set include_answer_text=false to leave the answers out and page through history with smaller responses.
 * @summary List an AEO prompt's checks
 */
export const AeoPromptsChecksParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoPromptsChecksQueryEngineMax = 64

export const aeoPromptsChecksQueryIncludeAnswerTextDefault = true
export const aeoPromptsChecksQueryLimitMax = 100

export const AeoPromptsChecksQueryParams = () => zod.object({
    engine: zod
        .string()
        .min(1)
        .max(aeoPromptsChecksQueryEngineMax)
        .optional()
        .describe("Only list checks from this answer engine, for example 'claude-web-search'."),
    include_answer_text: zod
        .boolean()
        .default(aeoPromptsChecksQueryIncludeAnswerTextDefault)
        .describe(
            "Set to false to return answer_text as null on every check. Use it to page through history without the engines' answers."
        ),
    limit: zod.number().max(aeoPromptsChecksQueryLimitMax).optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    since: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Only list checks that ran at or after this time, in ISO 8601 (for example 2026-10-01T00:00:00Z).'),
    version: zod.number().min(1).optional().describe('Only list checks that ran this version of the prompt.'),
})

/**
 * Gets citation and brand-mention totals per answer engine for one prompt, plus, for the last 30 days in the project's timezone, per-day counts, which engines cite which domains, brand sentiment per engine, and the words of the web searches the engines ran.
 * @summary Get an AEO prompt's citation stats
 */
export const AeoPromptsStatsParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Lists every version of a prompt's text, newest first. A text edit adds a version, and one of them is current.
 * @summary List an AEO prompt's versions
 */
export const AeoPromptsVersionsParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Adds prompts to the project's AEO prompt set, or updates the topic and visibility of prompts that already exist. Existing prompts keep their active state. Prompts whose text matches an archived prompt are skipped.
 * @summary Import AEO prompts
 */
export const AeoPromptsBulkImportParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoPromptsBulkImportBodyPromptsItemPromptMax = 10000

export const aeoPromptsBulkImportBodyPromptsItemTopicMax = 200

export const aeoPromptsBulkImportBodyPromptsItemExternalVisibilityMin = 0
export const aeoPromptsBulkImportBodyPromptsItemExternalVisibilityMax = 100

export const aeoPromptsBulkImportBodyPromptsMax = 2000

export const AeoPromptsBulkImportBody = () => zod.object({
    prompts: zod
        .array(
            zod.object({
                prompt: zod
                    .string()
                    .max(aeoPromptsBulkImportBodyPromptsItemPromptMax)
                    .describe(
                        'The question to ask the answer engines, as a user would phrase it. Matching ignores case and whitespace, so a re-import updates the existing prompt.'
                    ),
                topic: zod
                    .string()
                    .max(aeoPromptsBulkImportBodyPromptsItemTopicMax)
                    .optional()
                    .describe('Theme the prompt belongs to. The runner alternates between topics on each run.'),
                external_visibility: zod
                    .number()
                    .min(aeoPromptsBulkImportBodyPromptsItemExternalVisibilityMin)
                    .max(aeoPromptsBulkImportBodyPromptsItemExternalVisibilityMax)
                    .nullish()
                    .describe(
                        'Share of answers (0-100) that mention the brand for this prompt, as reported by the tool the prompt set came from. Kept to benchmark against our own citation rate.'
                    ),
                origin: zod
                    .enum(['api', 'suggestion'])
                    .describe('\* `api` - Api\n\* `suggestion` - Suggestion')
                    .optional()
                    .describe(
                        "Where the prompt text came from: api (written by a person) or suggestion (picked from aeo_prompts\/suggest). Stored in the prompt's evidence so suggested prompts can be audited later.\n\n\* `api` - Api\n\* `suggestion` - Suggestion"
                    ),
            })
        )
        .min(1)
        .max(aeoPromptsBulkImportBodyPromptsMax)
        .describe('Prompts to add or update, at most 2000 per request.'),
})

/**
 * Creates a dashboard named 'AI visibility weekly' with SQL insights over the citation checks of non-branded prompts: visibility and citation rate for the last 7 complete days against the 7 before, visibility per topic, the pages to watch per topic, and an 8-week trend. The queries read the brand catalog when they run, so they follow catalog edits. Each call creates a new dashboard. Subscribe to it with the subscriptions API to get it weekly in Slack or email.
 * @summary Create the AI visibility weekly dashboard
 */
export const AeoPromptsCreateDashboardParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Gets an overview of the project's whole AEO prompt set for the last 'days' days (default 30) in the project's timezone: how many prompts are tracked, how many checks ran, the citation rate and the brand-mention rate, the same counts for the window before it, the current window split per answer engine (Claude, ChatGPT/OpenAI, Exa) and per topic, and the domains the engines cited most. Those counts cover web-search checks; a prompt's own stats split every engine, no-search ones included. Pass 'branded' to count only the checks whose prompt names the brand, or only the ones whose prompt does not, 'engine' to count one answer engine, and 'topic' to count one topic.
 * @summary Get the AEO prompt set overview
 */
export const AeoPromptsOverviewParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoPromptsOverviewQueryBrandedDefault = `all`
export const aeoPromptsOverviewQueryDaysDefault = 30
export const aeoPromptsOverviewQueryDaysMax = 90

export const aeoPromptsOverviewQueryEngineMax = 64

export const aeoPromptsOverviewQueryTopicMax = 200

export const AeoPromptsOverviewQueryParams = () => zod.object({
    branded: zod
        .enum(['all', 'branded', 'non_branded'])
        .default(aeoPromptsOverviewQueryBrandedDefault)
        .describe(
            "Which checks to count, by the prompt as it ran: 'all' (default), 'branded' (the prompt names the brand) or 'non_branded'. Every count, the window before included, uses the same checks. Use 'non_branded' to judge visibility, since a prompt that names the brand almost always gets an answer that mentions it. A prompt is branded when its text names the brand: the registrable name of a target domain as a word, case ignored, so 'example' and 'example.com' both name example.com. Branded prompts almost always get answers that mention the brand.\n\n\* `all` - All\n\* `branded` - Branded\n\* `non_branded` - Non-branded"
        ),
    days: zod
        .number()
        .min(1)
        .max(aeoPromptsOverviewQueryDaysMax)
        .default(aeoPromptsOverviewQueryDaysDefault)
        .describe("Length of the window in days, ending today in the project's timezone. Default 30, at most 90."),
    engine: zod
        .string()
        .max(aeoPromptsOverviewQueryEngineMax)
        .nullish()
        .describe(
            "Only count checks from this answer engine, for example 'claude-web-search'. Omit to count every engine."
        ),
    topic: zod
        .string()
        .max(aeoPromptsOverviewQueryTopicMax)
        .nullish()
        .describe(
            'Only count checks that ran with this prompt topic. A prompt moved to another topic keeps its past checks under the old one. An empty value counts the checks of prompts that had no topic. Omit to count every topic.'
        ),
})

/**
 * Gets how often AI answers named the project against its competitors over the last 'days' days (default 30) in the project's timezone, with the same share for the window before, a daily series, and the domains and pages the engines cited most. Competitors are derived from the cited domains. Pass 'branded' to count only the checks whose prompt names the brand, or only the ones whose prompt does not, 'engine' to count one answer engine, and 'topic' to count one topic.
 * @summary Get AEO brand rankings
 */
export const AeoPromptsRankingsParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoPromptsRankingsQueryBrandedDefault = `all`
export const aeoPromptsRankingsQueryDaysDefault = 30
export const aeoPromptsRankingsQueryDaysMax = 90

export const aeoPromptsRankingsQueryEngineMax = 64

export const aeoPromptsRankingsQueryTopicMax = 200

export const AeoPromptsRankingsQueryParams = () => zod.object({
    branded: zod
        .enum(['all', 'branded', 'non_branded'])
        .default(aeoPromptsRankingsQueryBrandedDefault)
        .describe(
            "Which checks to count, by the prompt as it ran: 'all' (default), 'branded' (the prompt names the brand) or 'non_branded'. Every count, the window before included, uses the same checks. Use 'non_branded' to judge visibility, since a prompt that names the brand almost always gets an answer that mentions it. A prompt is branded when its text names the brand: the registrable name of a target domain as a word, case ignored, so 'example' and 'example.com' both name example.com. Branded prompts almost always get answers that mention the brand.\n\n\* `all` - All\n\* `branded` - Branded\n\* `non_branded` - Non-branded"
        ),
    days: zod
        .number()
        .min(1)
        .max(aeoPromptsRankingsQueryDaysMax)
        .default(aeoPromptsRankingsQueryDaysDefault)
        .describe("Length of the window in days, ending today in the project's timezone. Default 30, at most 90."),
    engine: zod
        .string()
        .max(aeoPromptsRankingsQueryEngineMax)
        .nullish()
        .describe(
            "Only count checks from this answer engine, for example 'claude-web-search'. Omit to count every engine."
        ),
    topic: zod
        .string()
        .max(aeoPromptsRankingsQueryTopicMax)
        .nullish()
        .describe(
            'Only count checks that ran with this prompt topic. A prompt moved to another topic keeps its past checks under the old one. An empty value counts the checks of prompts that had no topic. Omit to count every topic.'
        ),
})

/**
 * Suggests prompts to track for a site. Requires AI data processing approved for the organization. PostHog reads the site with web search and writes questions a buyer would ask an AI assistant, each labeled with a topic, a circle, a funnel stage and whether it names the brand. Nothing is saved: import the prompts you keep with bulk_import. Prompts the project already tracks are left out. Returns a pending job right away; poll GET aeo_prompts/suggest/<id>/ until it completes, which takes up to a few minutes.
 * @summary Suggest AEO prompts
 */
export const AeoPromptsSuggestParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoPromptsSuggestBodyDomainMax = 200

export const aeoPromptsSuggestBodyBrandMax = 200

export const aeoPromptsSuggestBodyDescriptionMax = 1000

export const aeoPromptsSuggestBodyCompetitorsItemMax = 200

export const aeoPromptsSuggestBodyCompetitorsMax = 20

export const aeoPromptsSuggestBodyTopicsItemMax = 200

export const aeoPromptsSuggestBodyTopicsMax = 20

export const aeoPromptsSuggestBodyCountDefault = 20
export const aeoPromptsSuggestBodyCountMax = 50

export const AeoPromptsSuggestBody = () => zod.object({
    domain: zod
        .string()
        .max(aeoPromptsSuggestBodyDomainMax)
        .describe('The site to suggest prompts for, for example posthog.com. The model reads it with web search.'),
    brand: zod
        .string()
        .max(aeoPromptsSuggestBodyBrandMax)
        .optional()
        .describe('The brand name. Inferred from the site when empty.'),
    description: zod
        .string()
        .max(aeoPromptsSuggestBodyDescriptionMax)
        .optional()
        .describe('What the product does and who it is for. Inferred from the site when empty.'),
    competitors: zod
        .array(zod.string().max(aeoPromptsSuggestBodyCompetitorsItemMax))
        .max(aeoPromptsSuggestBodyCompetitorsMax)
        .optional()
        .describe('Competitor names or domains. The model picks the main ones when empty.'),
    topics: zod
        .array(zod.string().max(aeoPromptsSuggestBodyTopicsItemMax))
        .max(aeoPromptsSuggestBodyTopicsMax)
        .optional()
        .describe('Topics to spread the prompts across. The model picks 3 to 6 when empty.'),
    count: zod
        .number()
        .min(1)
        .max(aeoPromptsSuggestBodyCountMax)
        .default(aeoPromptsSuggestBodyCountDefault)
        .describe('How many prompts to suggest, at most 50.'),
})

/**
 * Gets a prompt suggestion job started with POST aeo_prompts/suggest/. status is pending while PostHog works, then completed with the suggestions or failed with an error. Jobs expire an hour after their last update.
 * @summary Get AEO prompt suggestions
 */
export const aeoPromptsSuggestionRetrievePathJobIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const AeoPromptsSuggestionRetrieveParams = () => zod.object({
    job_id: zod.string().regex(aeoPromptsSuggestionRetrievePathJobIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Lists the topics in the project's AEO prompt set, with the number of prompts in each.
 * @summary List AEO prompt topics
 */
export const AeoPromptsTopicsParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Sets up AI visibility tracking for the project in one job. Requires AI data processing approved for the organization. In order, it adds the site as the project's own brand, has PostHog suggest 20 prompts and saves them, and has PostHog suggest 20 keywords and saves them. With run_first_check the prompts are saved active and a first citation check run is queued with the enabled engines; each check is a paid call to every enabled engine, and each engine keeps checking active prompts on its schedule. Without it, new prompts are saved paused, so nothing is checked or spent until they are turned on. A step the project already covers is skipped: an own brand exists, 10 or more unarchived prompts, 10 or more keywords, or any check already recorded. With engines, the chosen engines are turned on and every other one off before the job starts. Returns a pending job right away; poll GET aeo_setup/<id>/ until it completes, which takes a few minutes. Running it again only fills the gaps.
 * @summary Set up AI visibility
 */
export const AeoSetupCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoSetupCreateBodyDomainMax = 200

export const aeoSetupCreateBodyBrandMax = 200

export const aeoSetupCreateBodyDescriptionMax = 1000

export const aeoSetupCreateBodyEnginesItemMax = 64

export const aeoSetupCreateBodyEnginesMax = 20

export const aeoSetupCreateBodyRunFirstCheckDefault = false
export const aeoSetupCreateBodyOnlyFirstRunDefault = false
export const aeoSetupCreateBodyActivatePausedPromptsDefault = false

export const AeoSetupCreateBody = () => zod.object({
    domain: zod
        .string()
        .max(aeoSetupCreateBodyDomainMax)
        .optional()
        .describe(
            "The project's site, for example example.com. It becomes the own brand, and PostHog reads it to suggest prompts and keywords. Required unless only_first_run is true."
        ),
    brand: zod
        .string()
        .max(aeoSetupCreateBodyBrandMax)
        .optional()
        .describe('The brand name. Inferred from the site when empty.'),
    description: zod
        .string()
        .max(aeoSetupCreateBodyDescriptionMax)
        .optional()
        .describe('What the product does and who it is for. Inferred from the site when empty.'),
    engines: zod
        .array(
            zod.string().max(aeoSetupCreateBodyEnginesItemMax).describe('An engine id from GET aeo_setup\/context\/.')
        )
        .max(aeoSetupCreateBodyEnginesMax)
        .optional()
        .describe(
            'The engines to track, by id. Every other engine is turned off before any run. An engine that is not available yet may be chosen: it stays on and PostHog starts checking with it once it is available. Leave it out to keep the current engine settings.'
        ),
    run_first_check: zod
        .boolean()
        .default(aeoSetupCreateBodyRunFirstCheckDefault)
        .describe(
            'Queue a first citation check run after setup. Each check is a paid call to every enabled engine. When false, setup saves the new prompts paused, so no checks run and nothing is spent until they are turned on, for example with only_first_run and activate_paused_prompts.'
        ),
    only_first_run: zod
        .boolean()
        .default(aeoSetupCreateBodyOnlyFirstRunDefault)
        .describe(
            'Queue a citation check run and nothing else: no brand, prompts or keywords, and no engine change. Use it when the project is already set up and should be checked now instead of on its schedule. Each check is a paid call to every enabled engine.'
        ),
    activate_paused_prompts: zod
        .boolean()
        .default(aeoSetupCreateBodyActivatePausedPromptsDefault)
        .describe(
            "With only_first_run, turn on every paused prompt before the run, such as the ones a setup without run_first_check saved paused. Turned-on prompts are checked on each engine's schedule from then on."
        ),
})

/**
 * Gets a setup job started with POST aeo_setup/, with the state of each step. Jobs expire an hour after their last update.
 * @summary Get AEO setup job
 */
export const aeoSetupRetrievePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const AeoSetupRetrieveParams = () => zod.object({
    id: zod.string().regex(aeoSetupRetrievePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Gets what PostHog already knows about the project for AI visibility setup: the domains it may be about, from its own brands, authorized URLs, recording domains and pageview hosts, and how many prompts, keywords and checks it has. Use the first website as the default domain for POST aeo_setup/.
 * @summary Get AEO setup context
 */
export const AeoSetupContextParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
