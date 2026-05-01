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
