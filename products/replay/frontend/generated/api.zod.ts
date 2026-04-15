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
 * Override list to include synthetic playlists
 */
export const sessionRecordingPlaylistsListResponseResultsItemNameMax = 400

export const sessionRecordingPlaylistsListResponseResultsItemDerivedNameMax = 400

export const sessionRecordingPlaylistsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const sessionRecordingPlaylistsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const sessionRecordingPlaylistsListResponseResultsItemCreatedByOneLastNameMax = 150

export const sessionRecordingPlaylistsListResponseResultsItemCreatedByOneEmailMax = 254

export const sessionRecordingPlaylistsListResponseResultsItemLastModifiedByOneDistinctIdMax = 200

export const sessionRecordingPlaylistsListResponseResultsItemLastModifiedByOneFirstNameMax = 150

export const sessionRecordingPlaylistsListResponseResultsItemLastModifiedByOneLastNameMax = 150

export const sessionRecordingPlaylistsListResponseResultsItemLastModifiedByOneEmailMax = 254

export const SessionRecordingPlaylistsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.number(),
            short_id: zod.string(),
            name: zod
                .string()
                .max(sessionRecordingPlaylistsListResponseResultsItemNameMax)
                .nullish()
                .describe('Human-readable name for the playlist.'),
            derived_name: zod.string().max(sessionRecordingPlaylistsListResponseResultsItemDerivedNameMax).nullish(),
            description: zod
                .string()
                .optional()
                .describe("Optional description of the playlist's purpose or contents."),
            pinned: zod.boolean().optional().describe('Whether this playlist is pinned to the top of the list.'),
            created_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(sessionRecordingPlaylistsListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(sessionRecordingPlaylistsListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(sessionRecordingPlaylistsListResponseResultsItemCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(sessionRecordingPlaylistsListResponseResultsItemCreatedByOneEmailMax),
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
            deleted: zod.boolean().optional().describe('Set to true to soft-delete the playlist.'),
            filters: zod
                .unknown()
                .optional()
                .describe(
                    "JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them."
                ),
            last_modified_at: zod.iso.datetime({}),
            last_modified_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(sessionRecordingPlaylistsListResponseResultsItemLastModifiedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(sessionRecordingPlaylistsListResponseResultsItemLastModifiedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(sessionRecordingPlaylistsListResponseResultsItemLastModifiedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(sessionRecordingPlaylistsListResponseResultsItemLastModifiedByOneEmailMax),
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
            recordings_counts: zod.record(
                zod.string(),
                zod.record(zod.string(), zod.union([zod.number(), zod.boolean()]).nullable())
            ),
            type: zod
                .union([
                    zod.enum(['collection', 'filters']).describe('* `collection` - Collection\n* `filters` - Filters'),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    "Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.\n\n* `collection` - Collection\n* `filters` - Filters"
                ),
            is_synthetic: zod.boolean().describe('Return whether this is a synthetic playlist'),
            _create_in_folder: zod.string().optional(),
        })
    ),
})

export const sessionRecordingPlaylistsCreateBodyNameMax = 400

export const sessionRecordingPlaylistsCreateBodyDerivedNameMax = 400

export const SessionRecordingPlaylistsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(sessionRecordingPlaylistsCreateBodyNameMax)
        .nullish()
        .describe('Human-readable name for the playlist.'),
    derived_name: zod.string().max(sessionRecordingPlaylistsCreateBodyDerivedNameMax).nullish(),
    description: zod.string().optional().describe("Optional description of the playlist's purpose or contents."),
    pinned: zod.boolean().optional().describe('Whether this playlist is pinned to the top of the list.'),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the playlist.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            "JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them."
        ),
    type: zod
        .union([
            zod.enum(['collection', 'filters']).describe('* `collection` - Collection\n* `filters` - Filters'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            "Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.\n\n* `collection` - Collection\n* `filters` - Filters"
        ),
    _create_in_folder: zod.string().optional(),
})

export const sessionRecordingPlaylistsRetrieveResponseNameMax = 400

export const sessionRecordingPlaylistsRetrieveResponseDerivedNameMax = 400

export const sessionRecordingPlaylistsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const sessionRecordingPlaylistsRetrieveResponseCreatedByOneFirstNameMax = 150

export const sessionRecordingPlaylistsRetrieveResponseCreatedByOneLastNameMax = 150

export const sessionRecordingPlaylistsRetrieveResponseCreatedByOneEmailMax = 254

export const sessionRecordingPlaylistsRetrieveResponseLastModifiedByOneDistinctIdMax = 200

export const sessionRecordingPlaylistsRetrieveResponseLastModifiedByOneFirstNameMax = 150

export const sessionRecordingPlaylistsRetrieveResponseLastModifiedByOneLastNameMax = 150

export const sessionRecordingPlaylistsRetrieveResponseLastModifiedByOneEmailMax = 254

export const SessionRecordingPlaylistsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    short_id: zod.string(),
    name: zod
        .string()
        .max(sessionRecordingPlaylistsRetrieveResponseNameMax)
        .nullish()
        .describe('Human-readable name for the playlist.'),
    derived_name: zod.string().max(sessionRecordingPlaylistsRetrieveResponseDerivedNameMax).nullish(),
    description: zod.string().optional().describe("Optional description of the playlist's purpose or contents."),
    pinned: zod.boolean().optional().describe('Whether this playlist is pinned to the top of the list.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(sessionRecordingPlaylistsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(sessionRecordingPlaylistsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(sessionRecordingPlaylistsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(sessionRecordingPlaylistsRetrieveResponseCreatedByOneEmailMax),
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
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the playlist.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            "JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them."
        ),
    last_modified_at: zod.iso.datetime({}),
    last_modified_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod
            .string()
            .max(sessionRecordingPlaylistsRetrieveResponseLastModifiedByOneDistinctIdMax)
            .nullish(),
        first_name: zod.string().max(sessionRecordingPlaylistsRetrieveResponseLastModifiedByOneFirstNameMax).optional(),
        last_name: zod.string().max(sessionRecordingPlaylistsRetrieveResponseLastModifiedByOneLastNameMax).optional(),
        email: zod.email().max(sessionRecordingPlaylistsRetrieveResponseLastModifiedByOneEmailMax),
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
    recordings_counts: zod.record(
        zod.string(),
        zod.record(zod.string(), zod.union([zod.number(), zod.boolean()]).nullable())
    ),
    type: zod
        .union([
            zod.enum(['collection', 'filters']).describe('* `collection` - Collection\n* `filters` - Filters'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            "Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.\n\n* `collection` - Collection\n* `filters` - Filters"
        ),
    is_synthetic: zod.boolean().describe('Return whether this is a synthetic playlist'),
    _create_in_folder: zod.string().optional(),
})

export const sessionRecordingPlaylistsUpdateBodyNameMax = 400

export const sessionRecordingPlaylistsUpdateBodyDerivedNameMax = 400

export const SessionRecordingPlaylistsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(sessionRecordingPlaylistsUpdateBodyNameMax)
        .nullish()
        .describe('Human-readable name for the playlist.'),
    derived_name: zod.string().max(sessionRecordingPlaylistsUpdateBodyDerivedNameMax).nullish(),
    description: zod.string().optional().describe("Optional description of the playlist's purpose or contents."),
    pinned: zod.boolean().optional().describe('Whether this playlist is pinned to the top of the list.'),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the playlist.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            "JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them."
        ),
    type: zod
        .union([
            zod.enum(['collection', 'filters']).describe('* `collection` - Collection\n* `filters` - Filters'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            "Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.\n\n* `collection` - Collection\n* `filters` - Filters"
        ),
    _create_in_folder: zod.string().optional(),
})

export const sessionRecordingPlaylistsUpdateResponseNameMax = 400

export const sessionRecordingPlaylistsUpdateResponseDerivedNameMax = 400

export const sessionRecordingPlaylistsUpdateResponseCreatedByOneDistinctIdMax = 200

export const sessionRecordingPlaylistsUpdateResponseCreatedByOneFirstNameMax = 150

export const sessionRecordingPlaylistsUpdateResponseCreatedByOneLastNameMax = 150

export const sessionRecordingPlaylistsUpdateResponseCreatedByOneEmailMax = 254

export const sessionRecordingPlaylistsUpdateResponseLastModifiedByOneDistinctIdMax = 200

export const sessionRecordingPlaylistsUpdateResponseLastModifiedByOneFirstNameMax = 150

export const sessionRecordingPlaylistsUpdateResponseLastModifiedByOneLastNameMax = 150

export const sessionRecordingPlaylistsUpdateResponseLastModifiedByOneEmailMax = 254

export const SessionRecordingPlaylistsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    short_id: zod.string(),
    name: zod
        .string()
        .max(sessionRecordingPlaylistsUpdateResponseNameMax)
        .nullish()
        .describe('Human-readable name for the playlist.'),
    derived_name: zod.string().max(sessionRecordingPlaylistsUpdateResponseDerivedNameMax).nullish(),
    description: zod.string().optional().describe("Optional description of the playlist's purpose or contents."),
    pinned: zod.boolean().optional().describe('Whether this playlist is pinned to the top of the list.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(sessionRecordingPlaylistsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(sessionRecordingPlaylistsUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(sessionRecordingPlaylistsUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(sessionRecordingPlaylistsUpdateResponseCreatedByOneEmailMax),
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
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the playlist.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            "JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them."
        ),
    last_modified_at: zod.iso.datetime({}),
    last_modified_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(sessionRecordingPlaylistsUpdateResponseLastModifiedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(sessionRecordingPlaylistsUpdateResponseLastModifiedByOneFirstNameMax).optional(),
        last_name: zod.string().max(sessionRecordingPlaylistsUpdateResponseLastModifiedByOneLastNameMax).optional(),
        email: zod.email().max(sessionRecordingPlaylistsUpdateResponseLastModifiedByOneEmailMax),
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
    recordings_counts: zod.record(
        zod.string(),
        zod.record(zod.string(), zod.union([zod.number(), zod.boolean()]).nullable())
    ),
    type: zod
        .union([
            zod.enum(['collection', 'filters']).describe('* `collection` - Collection\n* `filters` - Filters'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            "Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.\n\n* `collection` - Collection\n* `filters` - Filters"
        ),
    is_synthetic: zod.boolean().describe('Return whether this is a synthetic playlist'),
    _create_in_folder: zod.string().optional(),
})

export const sessionRecordingPlaylistsPartialUpdateBodyNameMax = 400

export const sessionRecordingPlaylistsPartialUpdateBodyDerivedNameMax = 400

export const SessionRecordingPlaylistsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(sessionRecordingPlaylistsPartialUpdateBodyNameMax)
        .nullish()
        .describe('Human-readable name for the playlist.'),
    derived_name: zod.string().max(sessionRecordingPlaylistsPartialUpdateBodyDerivedNameMax).nullish(),
    description: zod.string().optional().describe("Optional description of the playlist's purpose or contents."),
    pinned: zod.boolean().optional().describe('Whether this playlist is pinned to the top of the list.'),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the playlist.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            "JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them."
        ),
    type: zod
        .union([
            zod.enum(['collection', 'filters']).describe('* `collection` - Collection\n* `filters` - Filters'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            "Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.\n\n* `collection` - Collection\n* `filters` - Filters"
        ),
    _create_in_folder: zod.string().optional(),
})

export const sessionRecordingPlaylistsPartialUpdateResponseNameMax = 400

export const sessionRecordingPlaylistsPartialUpdateResponseDerivedNameMax = 400

export const sessionRecordingPlaylistsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const sessionRecordingPlaylistsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const sessionRecordingPlaylistsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const sessionRecordingPlaylistsPartialUpdateResponseCreatedByOneEmailMax = 254

export const sessionRecordingPlaylistsPartialUpdateResponseLastModifiedByOneDistinctIdMax = 200

export const sessionRecordingPlaylistsPartialUpdateResponseLastModifiedByOneFirstNameMax = 150

export const sessionRecordingPlaylistsPartialUpdateResponseLastModifiedByOneLastNameMax = 150

export const sessionRecordingPlaylistsPartialUpdateResponseLastModifiedByOneEmailMax = 254

export const SessionRecordingPlaylistsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    short_id: zod.string(),
    name: zod
        .string()
        .max(sessionRecordingPlaylistsPartialUpdateResponseNameMax)
        .nullish()
        .describe('Human-readable name for the playlist.'),
    derived_name: zod.string().max(sessionRecordingPlaylistsPartialUpdateResponseDerivedNameMax).nullish(),
    description: zod.string().optional().describe("Optional description of the playlist's purpose or contents."),
    pinned: zod.boolean().optional().describe('Whether this playlist is pinned to the top of the list.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod
            .string()
            .max(sessionRecordingPlaylistsPartialUpdateResponseCreatedByOneDistinctIdMax)
            .nullish(),
        first_name: zod.string().max(sessionRecordingPlaylistsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(sessionRecordingPlaylistsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(sessionRecordingPlaylistsPartialUpdateResponseCreatedByOneEmailMax),
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
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the playlist.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            "JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them."
        ),
    last_modified_at: zod.iso.datetime({}),
    last_modified_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod
            .string()
            .max(sessionRecordingPlaylistsPartialUpdateResponseLastModifiedByOneDistinctIdMax)
            .nullish(),
        first_name: zod
            .string()
            .max(sessionRecordingPlaylistsPartialUpdateResponseLastModifiedByOneFirstNameMax)
            .optional(),
        last_name: zod
            .string()
            .max(sessionRecordingPlaylistsPartialUpdateResponseLastModifiedByOneLastNameMax)
            .optional(),
        email: zod.email().max(sessionRecordingPlaylistsPartialUpdateResponseLastModifiedByOneEmailMax),
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
    recordings_counts: zod.record(
        zod.string(),
        zod.record(zod.string(), zod.union([zod.number(), zod.boolean()]).nullable())
    ),
    type: zod
        .union([
            zod.enum(['collection', 'filters']).describe('* `collection` - Collection\n* `filters` - Filters'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            "Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.\n\n* `collection` - Collection\n* `filters` - Filters"
        ),
    is_synthetic: zod.boolean().describe('Return whether this is a synthetic playlist'),
    _create_in_folder: zod.string().optional(),
})

export const sessionRecordingPlaylistsRecordingsCreateBodyNameMax = 400

export const sessionRecordingPlaylistsRecordingsCreateBodyDerivedNameMax = 400

export const SessionRecordingPlaylistsRecordingsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(sessionRecordingPlaylistsRecordingsCreateBodyNameMax)
        .nullish()
        .describe('Human-readable name for the playlist.'),
    derived_name: zod.string().max(sessionRecordingPlaylistsRecordingsCreateBodyDerivedNameMax).nullish(),
    description: zod.string().optional().describe("Optional description of the playlist's purpose or contents."),
    pinned: zod.boolean().optional().describe('Whether this playlist is pinned to the top of the list.'),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the playlist.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            "JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them."
        ),
    type: zod
        .union([
            zod.enum(['collection', 'filters']).describe('* `collection` - Collection\n* `filters` - Filters'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            "Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.\n\n* `collection` - Collection\n* `filters` - Filters"
        ),
    _create_in_folder: zod.string().optional(),
})

export const sessionRecordingsListResponseResultsItemSummaryOutcomeOneDescriptionMax = 10000

export const SessionRecordingsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            distinct_id: zod.string().nullable(),
            viewed: zod.boolean(),
            viewers: zod.array(zod.string()),
            recording_duration: zod.number(),
            active_seconds: zod.number().nullable(),
            inactive_seconds: zod.number().nullable(),
            start_time: zod.iso.datetime({}).nullable(),
            end_time: zod.iso.datetime({}).nullable(),
            click_count: zod.number().nullable(),
            keypress_count: zod.number().nullable(),
            mouse_activity_count: zod.number().nullable(),
            console_log_count: zod.number().nullable(),
            console_warn_count: zod.number().nullable(),
            console_error_count: zod.number().nullable(),
            start_url: zod.string().nullable(),
            person: zod
                .object({
                    id: zod.number().describe('Numeric person ID.'),
                    name: zod
                        .string()
                        .describe('Display name derived from person properties (email, name, or username).'),
                    distinct_ids: zod.array(zod.string()),
                    properties: zod
                        .unknown()
                        .optional()
                        .describe('Key-value map of person properties set via $set and $set_once operations.'),
                    created_at: zod.iso.datetime({}).describe('When this person was first seen (ISO 8601).'),
                    uuid: zod.uuid().describe('Unique identifier (UUID) for this person.'),
                    last_seen_at: zod.iso
                        .datetime({})
                        .nullable()
                        .describe('Timestamp of the last event from this person, or null.'),
                })
                .optional(),
            retention_period_days: zod.number().nullable(),
            expiry_time: zod.string(),
            recording_ttl: zod.string(),
            snapshot_source: zod.string().nullable(),
            snapshot_library: zod.string().nullable(),
            ongoing: zod.boolean(),
            activity_score: zod.number().nullable(),
            has_summary: zod.boolean(),
            summary_outcome: zod
                .object({
                    description: zod
                        .string()
                        .min(1)
                        .max(sessionRecordingsListResponseResultsItemSummaryOutcomeOneDescriptionMax)
                        .nullish(),
                    success: zod.boolean().nullish(),
                })
                .describe('Initial goal and session outcome coming from LLM.')
                .nullable(),
            external_references: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .describe('Load external references (linked issues) for this recording'),
        })
    ),
})

export const sessionRecordingsRetrieveResponseSummaryOutcomeOneDescriptionMax = 10000

export const SessionRecordingsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.string(),
    distinct_id: zod.string().nullable(),
    viewed: zod.boolean(),
    viewers: zod.array(zod.string()),
    recording_duration: zod.number(),
    active_seconds: zod.number().nullable(),
    inactive_seconds: zod.number().nullable(),
    start_time: zod.iso.datetime({}).nullable(),
    end_time: zod.iso.datetime({}).nullable(),
    click_count: zod.number().nullable(),
    keypress_count: zod.number().nullable(),
    mouse_activity_count: zod.number().nullable(),
    console_log_count: zod.number().nullable(),
    console_warn_count: zod.number().nullable(),
    console_error_count: zod.number().nullable(),
    start_url: zod.string().nullable(),
    person: zod
        .object({
            id: zod.number().describe('Numeric person ID.'),
            name: zod.string().describe('Display name derived from person properties (email, name, or username).'),
            distinct_ids: zod.array(zod.string()),
            properties: zod
                .unknown()
                .optional()
                .describe('Key-value map of person properties set via $set and $set_once operations.'),
            created_at: zod.iso.datetime({}).describe('When this person was first seen (ISO 8601).'),
            uuid: zod.uuid().describe('Unique identifier (UUID) for this person.'),
            last_seen_at: zod.iso
                .datetime({})
                .nullable()
                .describe('Timestamp of the last event from this person, or null.'),
        })
        .optional(),
    retention_period_days: zod.number().nullable(),
    expiry_time: zod.string(),
    recording_ttl: zod.string(),
    snapshot_source: zod.string().nullable(),
    snapshot_library: zod.string().nullable(),
    ongoing: zod.boolean(),
    activity_score: zod.number().nullable(),
    has_summary: zod.boolean(),
    summary_outcome: zod
        .object({
            description: zod
                .string()
                .min(1)
                .max(sessionRecordingsRetrieveResponseSummaryOutcomeOneDescriptionMax)
                .nullish(),
            success: zod.boolean().nullish(),
        })
        .describe('Initial goal and session outcome coming from LLM.')
        .nullable(),
    external_references: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe('Load external references (linked issues) for this recording'),
})

export const SessionRecordingsUpdateBody = /* @__PURE__ */ zod.object({
    person: zod
        .object({
            id: zod.number().describe('Numeric person ID.'),
            name: zod.string().describe('Display name derived from person properties (email, name, or username).'),
            distinct_ids: zod.array(zod.string()),
            properties: zod
                .unknown()
                .optional()
                .describe('Key-value map of person properties set via $set and $set_once operations.'),
            created_at: zod.iso.datetime({}).describe('When this person was first seen (ISO 8601).'),
            uuid: zod.uuid().describe('Unique identifier (UUID) for this person.'),
            last_seen_at: zod.iso
                .datetime({})
                .nullable()
                .describe('Timestamp of the last event from this person, or null.'),
        })
        .optional(),
})

export const sessionRecordingsUpdateResponseSummaryOutcomeOneDescriptionMax = 10000

export const SessionRecordingsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.string(),
    distinct_id: zod.string().nullable(),
    viewed: zod.boolean(),
    viewers: zod.array(zod.string()),
    recording_duration: zod.number(),
    active_seconds: zod.number().nullable(),
    inactive_seconds: zod.number().nullable(),
    start_time: zod.iso.datetime({}).nullable(),
    end_time: zod.iso.datetime({}).nullable(),
    click_count: zod.number().nullable(),
    keypress_count: zod.number().nullable(),
    mouse_activity_count: zod.number().nullable(),
    console_log_count: zod.number().nullable(),
    console_warn_count: zod.number().nullable(),
    console_error_count: zod.number().nullable(),
    start_url: zod.string().nullable(),
    person: zod
        .object({
            id: zod.number().describe('Numeric person ID.'),
            name: zod.string().describe('Display name derived from person properties (email, name, or username).'),
            distinct_ids: zod.array(zod.string()),
            properties: zod
                .unknown()
                .optional()
                .describe('Key-value map of person properties set via $set and $set_once operations.'),
            created_at: zod.iso.datetime({}).describe('When this person was first seen (ISO 8601).'),
            uuid: zod.uuid().describe('Unique identifier (UUID) for this person.'),
            last_seen_at: zod.iso
                .datetime({})
                .nullable()
                .describe('Timestamp of the last event from this person, or null.'),
        })
        .optional(),
    retention_period_days: zod.number().nullable(),
    expiry_time: zod.string(),
    recording_ttl: zod.string(),
    snapshot_source: zod.string().nullable(),
    snapshot_library: zod.string().nullable(),
    ongoing: zod.boolean(),
    activity_score: zod.number().nullable(),
    has_summary: zod.boolean(),
    summary_outcome: zod
        .object({
            description: zod
                .string()
                .min(1)
                .max(sessionRecordingsUpdateResponseSummaryOutcomeOneDescriptionMax)
                .nullish(),
            success: zod.boolean().nullish(),
        })
        .describe('Initial goal and session outcome coming from LLM.')
        .nullable(),
    external_references: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe('Load external references (linked issues) for this recording'),
})

export const SessionRecordingsPartialUpdateBody = /* @__PURE__ */ zod.object({
    person: zod
        .object({
            id: zod.number().describe('Numeric person ID.'),
            name: zod.string().describe('Display name derived from person properties (email, name, or username).'),
            distinct_ids: zod.array(zod.string()),
            properties: zod
                .unknown()
                .optional()
                .describe('Key-value map of person properties set via $set and $set_once operations.'),
            created_at: zod.iso.datetime({}).describe('When this person was first seen (ISO 8601).'),
            uuid: zod.uuid().describe('Unique identifier (UUID) for this person.'),
            last_seen_at: zod.iso
                .datetime({})
                .nullable()
                .describe('Timestamp of the last event from this person, or null.'),
        })
        .optional(),
})

export const sessionRecordingsPartialUpdateResponseSummaryOutcomeOneDescriptionMax = 10000

export const SessionRecordingsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.string(),
    distinct_id: zod.string().nullable(),
    viewed: zod.boolean(),
    viewers: zod.array(zod.string()),
    recording_duration: zod.number(),
    active_seconds: zod.number().nullable(),
    inactive_seconds: zod.number().nullable(),
    start_time: zod.iso.datetime({}).nullable(),
    end_time: zod.iso.datetime({}).nullable(),
    click_count: zod.number().nullable(),
    keypress_count: zod.number().nullable(),
    mouse_activity_count: zod.number().nullable(),
    console_log_count: zod.number().nullable(),
    console_warn_count: zod.number().nullable(),
    console_error_count: zod.number().nullable(),
    start_url: zod.string().nullable(),
    person: zod
        .object({
            id: zod.number().describe('Numeric person ID.'),
            name: zod.string().describe('Display name derived from person properties (email, name, or username).'),
            distinct_ids: zod.array(zod.string()),
            properties: zod
                .unknown()
                .optional()
                .describe('Key-value map of person properties set via $set and $set_once operations.'),
            created_at: zod.iso.datetime({}).describe('When this person was first seen (ISO 8601).'),
            uuid: zod.uuid().describe('Unique identifier (UUID) for this person.'),
            last_seen_at: zod.iso
                .datetime({})
                .nullable()
                .describe('Timestamp of the last event from this person, or null.'),
        })
        .optional(),
    retention_period_days: zod.number().nullable(),
    expiry_time: zod.string(),
    recording_ttl: zod.string(),
    snapshot_source: zod.string().nullable(),
    snapshot_library: zod.string().nullable(),
    ongoing: zod.boolean(),
    activity_score: zod.number().nullable(),
    has_summary: zod.boolean(),
    summary_outcome: zod
        .object({
            description: zod
                .string()
                .min(1)
                .max(sessionRecordingsPartialUpdateResponseSummaryOutcomeOneDescriptionMax)
                .nullish(),
            success: zod.boolean().nullish(),
        })
        .describe('Initial goal and session outcome coming from LLM.')
        .nullable(),
    external_references: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe('Load external references (linked issues) for this recording'),
})
