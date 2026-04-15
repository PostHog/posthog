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
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const notebooksListResponseResultsItemCreatedByOneFirstNameMax = 150

export const notebooksListResponseResultsItemCreatedByOneLastNameMax = 150

export const notebooksListResponseResultsItemCreatedByOneEmailMax = 254

export const notebooksListResponseResultsItemLastModifiedByOneDistinctIdMax = 200

export const notebooksListResponseResultsItemLastModifiedByOneFirstNameMax = 150

export const notebooksListResponseResultsItemLastModifiedByOneLastNameMax = 150

export const notebooksListResponseResultsItemLastModifiedByOneEmailMax = 254

export const NotebooksListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid().describe('UUID of the notebook.'),
            short_id: zod.string().describe('Short alphanumeric identifier used in URLs and API lookups.'),
            title: zod.string().nullable().describe('Title of the notebook.'),
            deleted: zod.boolean().describe('Whether the notebook has been soft-deleted.'),
            created_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(notebooksListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(notebooksListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(notebooksListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(notebooksListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            last_modified_at: zod.iso.datetime({}),
            last_modified_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(notebooksListResponseResultsItemLastModifiedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(notebooksListResponseResultsItemLastModifiedByOneFirstNameMax).optional(),
                last_name: zod.string().max(notebooksListResponseResultsItemLastModifiedByOneLastNameMax).optional(),
                email: zod.email().max(notebooksListResponseResultsItemLastModifiedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            user_access_level: zod
                .string()
                .nullable()
                .describe('The effective access level the user has for this object'),
            _create_in_folder: zod.string().optional(),
        })
    ),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksCreateBodyTitleMax = 256

export const notebooksCreateBodyVersionMin = -2147483648
export const notebooksCreateBodyVersionMax = 2147483647

export const NotebooksCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksCreateBodyVersionMin)
        .max(notebooksCreateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksRetrieveResponseTitleMax = 256

export const notebooksRetrieveResponseVersionMin = -2147483648
export const notebooksRetrieveResponseVersionMax = 2147483647

export const notebooksRetrieveResponseCreatedByOneDistinctIdMax = 200

export const notebooksRetrieveResponseCreatedByOneFirstNameMax = 150

export const notebooksRetrieveResponseCreatedByOneLastNameMax = 150

export const notebooksRetrieveResponseCreatedByOneEmailMax = 254

export const notebooksRetrieveResponseLastModifiedByOneDistinctIdMax = 200

export const notebooksRetrieveResponseLastModifiedByOneFirstNameMax = 150

export const notebooksRetrieveResponseLastModifiedByOneLastNameMax = 150

export const notebooksRetrieveResponseLastModifiedByOneEmailMax = 254

export const NotebooksRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid().describe('UUID of the notebook.'),
    short_id: zod.string().describe('Short alphanumeric identifier used in URLs and API lookups.'),
    title: zod.string().max(notebooksRetrieveResponseTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksRetrieveResponseVersionMin)
        .max(notebooksRetrieveResponseVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(notebooksRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(notebooksRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(notebooksRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(notebooksRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    last_modified_at: zod.iso.datetime({}),
    last_modified_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(notebooksRetrieveResponseLastModifiedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(notebooksRetrieveResponseLastModifiedByOneFirstNameMax).optional(),
        last_name: zod.string().max(notebooksRetrieveResponseLastModifiedByOneLastNameMax).optional(),
        email: zod.email().max(notebooksRetrieveResponseLastModifiedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksUpdateBodyTitleMax = 256

export const notebooksUpdateBodyVersionMin = -2147483648
export const notebooksUpdateBodyVersionMax = 2147483647

export const NotebooksUpdateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksUpdateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksUpdateBodyVersionMin)
        .max(notebooksUpdateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    _create_in_folder: zod.string().optional(),
})

export const notebooksUpdateResponseTitleMax = 256

export const notebooksUpdateResponseVersionMin = -2147483648
export const notebooksUpdateResponseVersionMax = 2147483647

export const notebooksUpdateResponseCreatedByOneDistinctIdMax = 200

export const notebooksUpdateResponseCreatedByOneFirstNameMax = 150

export const notebooksUpdateResponseCreatedByOneLastNameMax = 150

export const notebooksUpdateResponseCreatedByOneEmailMax = 254

export const notebooksUpdateResponseLastModifiedByOneDistinctIdMax = 200

export const notebooksUpdateResponseLastModifiedByOneFirstNameMax = 150

export const notebooksUpdateResponseLastModifiedByOneLastNameMax = 150

export const notebooksUpdateResponseLastModifiedByOneEmailMax = 254

export const NotebooksUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid().describe('UUID of the notebook.'),
    short_id: zod.string().describe('Short alphanumeric identifier used in URLs and API lookups.'),
    title: zod.string().max(notebooksUpdateResponseTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksUpdateResponseVersionMin)
        .max(notebooksUpdateResponseVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(notebooksUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(notebooksUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(notebooksUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(notebooksUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    last_modified_at: zod.iso.datetime({}),
    last_modified_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(notebooksUpdateResponseLastModifiedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(notebooksUpdateResponseLastModifiedByOneFirstNameMax).optional(),
        last_name: zod.string().max(notebooksUpdateResponseLastModifiedByOneLastNameMax).optional(),
        email: zod.email().max(notebooksUpdateResponseLastModifiedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksPartialUpdateBodyTitleMax = 256

export const notebooksPartialUpdateBodyVersionMin = -2147483648
export const notebooksPartialUpdateBodyVersionMax = 2147483647

export const NotebooksPartialUpdateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksPartialUpdateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksPartialUpdateBodyVersionMin)
        .max(notebooksPartialUpdateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    _create_in_folder: zod.string().optional(),
})

export const notebooksPartialUpdateResponseTitleMax = 256

export const notebooksPartialUpdateResponseVersionMin = -2147483648
export const notebooksPartialUpdateResponseVersionMax = 2147483647

export const notebooksPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const notebooksPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const notebooksPartialUpdateResponseCreatedByOneLastNameMax = 150

export const notebooksPartialUpdateResponseCreatedByOneEmailMax = 254

export const notebooksPartialUpdateResponseLastModifiedByOneDistinctIdMax = 200

export const notebooksPartialUpdateResponseLastModifiedByOneFirstNameMax = 150

export const notebooksPartialUpdateResponseLastModifiedByOneLastNameMax = 150

export const notebooksPartialUpdateResponseLastModifiedByOneEmailMax = 254

export const NotebooksPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid().describe('UUID of the notebook.'),
    short_id: zod.string().describe('Short alphanumeric identifier used in URLs and API lookups.'),
    title: zod.string().max(notebooksPartialUpdateResponseTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksPartialUpdateResponseVersionMin)
        .max(notebooksPartialUpdateResponseVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(notebooksPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(notebooksPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(notebooksPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(notebooksPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    last_modified_at: zod.iso.datetime({}),
    last_modified_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(notebooksPartialUpdateResponseLastModifiedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(notebooksPartialUpdateResponseLastModifiedByOneFirstNameMax).optional(),
        last_name: zod.string().max(notebooksPartialUpdateResponseLastModifiedByOneLastNameMax).optional(),
        email: zod.email().max(notebooksPartialUpdateResponseLastModifiedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksHogqlExecuteCreateBodyTitleMax = 256

export const notebooksHogqlExecuteCreateBodyVersionMin = -2147483648
export const notebooksHogqlExecuteCreateBodyVersionMax = 2147483647

export const NotebooksHogqlExecuteCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksHogqlExecuteCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksHogqlExecuteCreateBodyVersionMin)
        .max(notebooksHogqlExecuteCreateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelConfigCreateBodyTitleMax = 256

export const notebooksKernelConfigCreateBodyVersionMin = -2147483648
export const notebooksKernelConfigCreateBodyVersionMax = 2147483647

export const NotebooksKernelConfigCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelConfigCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksKernelConfigCreateBodyVersionMin)
        .max(notebooksKernelConfigCreateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelExecuteCreateBodyTitleMax = 256

export const notebooksKernelExecuteCreateBodyVersionMin = -2147483648
export const notebooksKernelExecuteCreateBodyVersionMax = 2147483647

export const NotebooksKernelExecuteCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelExecuteCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksKernelExecuteCreateBodyVersionMin)
        .max(notebooksKernelExecuteCreateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelExecuteStreamCreateBodyTitleMax = 256

export const notebooksKernelExecuteStreamCreateBodyVersionMin = -2147483648
export const notebooksKernelExecuteStreamCreateBodyVersionMax = 2147483647

export const NotebooksKernelExecuteStreamCreateBody = /* @__PURE__ */ zod.object({
    title: zod
        .string()
        .max(notebooksKernelExecuteStreamCreateBodyTitleMax)
        .nullish()
        .describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksKernelExecuteStreamCreateBodyVersionMin)
        .max(notebooksKernelExecuteStreamCreateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelRestartCreateBodyTitleMax = 256

export const notebooksKernelRestartCreateBodyVersionMin = -2147483648
export const notebooksKernelRestartCreateBodyVersionMax = 2147483647

export const NotebooksKernelRestartCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelRestartCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksKernelRestartCreateBodyVersionMin)
        .max(notebooksKernelRestartCreateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelStartCreateBodyTitleMax = 256

export const notebooksKernelStartCreateBodyVersionMin = -2147483648
export const notebooksKernelStartCreateBodyVersionMax = 2147483647

export const NotebooksKernelStartCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelStartCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksKernelStartCreateBodyVersionMin)
        .max(notebooksKernelStartCreateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    _create_in_folder: zod.string().optional(),
})

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelStopCreateBodyTitleMax = 256

export const notebooksKernelStopCreateBodyVersionMin = -2147483648
export const notebooksKernelStopCreateBodyVersionMax = 2147483647

export const NotebooksKernelStopCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(notebooksKernelStopCreateBodyTitleMax).nullish().describe('Title of the notebook.'),
    content: zod.unknown().nullish().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    version: zod
        .number()
        .min(notebooksKernelStopCreateBodyVersionMin)
        .max(notebooksKernelStopCreateBodyVersionMax)
        .optional()
        .describe(
            'Version number for optimistic concurrency control. Must match the current version when updating content.'
        ),
    deleted: zod.boolean().optional().describe('Whether the notebook has been soft-deleted.'),
    _create_in_folder: zod.string().optional(),
})
