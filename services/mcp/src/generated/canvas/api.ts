/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 11 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Canvases: agent-built sandboxed browser apps, filed into channels.
 *
 * Source is versioned per publish and built server-side; the canvas app
 * renders the published build's artifact from the isolated artifact origin.
 */
export const CanvasesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const CanvasesListQueryParams = /* @__PURE__ */ zod.object({
    channel: zod.string().optional().describe('Only return canvases in this channel.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Create a new, empty canvas in a channel; give it source by publishing a project.
 */
export const CanvasesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const canvasesCreateBodyNameMax = 400

export const canvasesCreateBodyTemplateIdDefault = `freeform`
export const canvasesCreateBodyTemplateIdMax = 64

export const CanvasesCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(canvasesCreateBodyNameMax).describe('Display name for the canvas.'),
        channel_id: zod.string().describe('Id of the channel the canvas belongs to.'),
        template_id: zod
            .string()
            .max(canvasesCreateBodyTemplateIdMax)
            .default(canvasesCreateBodyTemplateIdDefault)
            .describe('Canvas template identifier.'),
    })
    .describe('Payload for creating a new, empty canvas in a channel.')

/**
 * Read the canvas's build lifecycle: live pointers plus recent builds.
 *
 * A publish queues a build; poll this until it is ready (the live pointer
 * advances) or failed (fix the error diagnostics and publish again — the
 * last good build stays live).
 */
export const CanvasesBuildsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this canvas.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const CanvasesBuildsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    version_id: zod
        .string()
        .optional()
        .describe('Include the retained ready build for this historical source version.'),
})

/**
 * Stage a complete source project as a draft version and build it, without publishing.
 *
 * The draft gets the same validation, versioning, and server-side build as
 * a publish, but the canvas's head and live build never move, so nothing
 * changes for viewers. Promote the version with `promote` to make it live.
 * The response reports how the draft's declared capabilities widen the
 * current head's, so growth in access can be reviewed before it ships.
 * No version guard applies: a draft conflicts with nothing.
 */
export const CanvasesDraftCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this canvas.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const canvasesDraftCreateBodyProjectOneAssetsContentMax = 2796204

export const canvasesDraftCreateBodyProjectOneAssetsContentRegExp = new RegExp(
    '^(?:[A-Za-z0-9+\/]{4})\*(?:[A-Za-z0-9+\/]{2}==|[A-Za-z0-9+\/]{3}=)?$'
)
export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax = 128

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax = 100

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax = 200

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax = 100

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogStateMax = 2

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogActionsItemMax = 64

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogActionsMax = 32

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogAgentRequestsDefault = false
export const canvasesDraftCreateBodyProjectOneCapabilitiesOneNetworkOriginsItemMax = 2048

export const canvasesDraftCreateBodyProjectOneCapabilitiesOneNetworkOriginsMax = 20

export const CanvasesDraftCreateBody = /* @__PURE__ */ zod
    .object({
        project: zod
            .object({
                schemaVersion: zod.number().describe('Source-project schema version. Currently always 1.'),
                files: zod
                    .record(zod.string(), zod.string())
                    .describe("Project files keyed by relative path (forward slashes, no '..')."),
                assets: zod
                    .record(
                        zod.string(),
                        zod.object({
                            encoding: zod.enum(['base64']).describe('\* `base64` - base64'),
                            contentType: zod
                                .enum([
                                    'image/png',
                                    'image/jpeg',
                                    'image/gif',
                                    'image/webp',
                                    'image/svg+xml',
                                    'font/woff',
                                    'font/woff2',
                                    'application/wasm',
                                    'application/octet-stream',
                                ])
                                .describe(
                                    '\* `image\/png` - image\/png\n\* `image\/jpeg` - image\/jpeg\n\* `image\/gif` - image\/gif\n\* `image\/webp` - image\/webp\n\* `image\/svg+xml` - image\/svg+xml\n\* `font\/woff` - font\/woff\n\* `font\/woff2` - font\/woff2\n\* `application\/wasm` - application\/wasm\n\* `application\/octet-stream` - application\/octet-stream'
                                ),
                            content: zod
                                .string()
                                .max(canvasesDraftCreateBodyProjectOneAssetsContentMax)
                                .regex(canvasesDraftCreateBodyProjectOneAssetsContentRegExp),
                        })
                    )
                    .optional()
                    .describe('Optional base64-encoded binary assets keyed by safe project-relative paths.'),
                entryHtml: zod.string().describe('The project\'s entry HTML file. Currently always \"index.html\".'),
                dependencies: zod
                    .record(zod.string(), zod.string())
                    .optional()
                    .describe(
                        'Exact-version dependencies, restricted to the platform-supported set at its pinned versions.'
                    ),
                canvasSdkVersion: zod
                    .string()
                    .optional()
                    .describe('Version of the host-injected `ph` canvas SDK the project targets.'),
                capabilities: zod
                    .object({
                        posthog: zod.object({
                            insights: zod
                                .array(
                                    zod
                                        .string()
                                        .max(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax)
                                )
                                .max(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax),
                            inlineQueries: zod.boolean(),
                            captureEvents: zod
                                .array(
                                    zod
                                        .string()
                                        .max(
                                            canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax
                                        )
                                )
                                .max(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax),
                            state: zod
                                .array(zod.enum(['user', 'shared']).describe('\* `user` - user\n\* `shared` - shared'))
                                .max(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogStateMax)
                                .optional()
                                .describe(
                                    "State scopes the canvas may use via ph.state: 'user' (private to each viewer) and\/or 'shared' (one value per canvas, team-visible)."
                                ),
                            actions: zod
                                .array(
                                    zod
                                        .string()
                                        .max(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogActionsItemMax)
                                )
                                .max(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogActionsMax)
                                .optional()
                                .describe(
                                    "Registered action verbs the canvas may invoke via ph.actions (e.g. 'annotations.create', 'tasks.create'). Each executes as the viewer; declaring one shows it in the promote review."
                                ),
                            agentRequests: zod
                                .boolean()
                                .default(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogAgentRequestsDefault),
                        }),
                        network: zod.object({
                            origins: zod
                                .array(
                                    zod.url().max(canvasesDraftCreateBodyProjectOneCapabilitiesOneNetworkOriginsItemMax)
                                )
                                .max(canvasesDraftCreateBodyProjectOneCapabilitiesOneNetworkOriginsMax),
                        }),
                    })
                    .optional()
                    .describe(
                        'Bounded capabilities frozen into the built artifact. Declare every insight short id the canvas loads, every event it captures, and inlineQueries when it runs ad-hoc HogQL — the host enforces these at runtime and validation rejects undeclared `ph` calls. Network origins must be exact HTTPS origins. Data fetched by canvas code can be sent to those origins.'
                    ),
            })
            .describe("A canvas's multi-file source project — the canonical write format for canvas source.")
            .describe('The complete source project to stage as a draft.'),
        prompt: zod
            .string()
            .optional()
            .describe("Short description of the change, stored on the draft's version history entry."),
    })
    .describe('Payload for staging a complete source project as a draft build.')

/**
 * The canvas's staged draft versions, newest first, each with its latest build status.
 *
 * A draft is a version that was built but never made the head. Preview one
 * with `source?version_id=`, then make it live with `promote`.
 */
export const CanvasesDraftsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this canvas.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const CanvasesDraftsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Publish per-file edits against the canvas's current source project.
 *
 * Diff-aware alternative to sending the complete project: each operation
 * sets a file's content or (content null) deletes it, applied to the head
 * the caller read. `expected_current_version_id` is mandatory here —
 * relative edits against an unverified base could silently merge into
 * someone else's newer work.
 */
export const CanvasesEditCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this canvas.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const canvasesEditCreateBodyNameMax = 400

export const CanvasesEditCreateBody = /* @__PURE__ */ zod
    .object({
        operations: zod
            .array(
                zod
                    .object({
                        path: zod
                            .string()
                            .describe(
                                'Project-relative path of the file to write or delete (e.g. \"src\/canvas.tsx\").'
                            ),
                        content: zod
                            .string()
                            .nullish()
                            .describe("The file's complete new content. Null (or omitted) deletes the file."),
                    })
                    .describe("One per-file edit: set a file's content, or delete it.")
            )
            .describe("Edits applied in order to the canvas's current source project."),
        prompt: zod
            .string()
            .optional()
            .describe('Short description of the change, stored on the appended version history entry.'),
        name: zod
            .string()
            .max(canvasesEditCreateBodyNameMax)
            .optional()
            .describe('Optional new display name for the canvas.'),
        expected_current_version_id: zod
            .string()
            .nullable()
            .describe(
                'Required optimistic-concurrency guard: the current_version_id the edits are based on (null when the canvas has never been published). Diff edits against a moved head are rejected with 409 version_conflict — they cannot be published unguarded.'
            ),
    })
    .describe("Payload for publishing per-file edits against the canvas's current source.")

/**
 * Make a draft version the canvas's live head.
 *
 * A draft whose build is ready goes live immediately, with no rebuild;
 * otherwise a fresh build is queued. Returns that build.
 */
export const CanvasesPromoteCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this canvas.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const CanvasesPromoteCreateBody = /* @__PURE__ */ zod
    .object({
        version_id: zod.string().describe('Id of the draft source version to make live.'),
        expected_current_version_id: zod
            .string()
            .nullable()
            .describe(
                'Current source version observed before requesting the promote (null when the canvas has never been published). A moved head is rejected with 409 version_conflict.'
            ),
    })
    .describe("Payload for promoting a draft version to the canvas's live head.")

/**
 * Publish a complete source project as the canvas's new head version.
 *
 * Validation errors reject the publish (400) and leave the canvas
 * untouched; a stale `expected_current_version_id` is rejected with 409.
 * A successful publish queues a server-side build.
 */
export const CanvasesPublishCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this canvas.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const canvasesPublishCreateBodyProjectOneAssetsContentMax = 2796204

export const canvasesPublishCreateBodyProjectOneAssetsContentRegExp = new RegExp(
    '^(?:[A-Za-z0-9+\/]{4})\*(?:[A-Za-z0-9+\/]{2}==|[A-Za-z0-9+\/]{3}=)?$'
)
export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax = 128

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax = 100

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax = 200

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax = 100

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogStateMax = 2

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogActionsItemMax = 64

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogActionsMax = 32

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogAgentRequestsDefault = false
export const canvasesPublishCreateBodyProjectOneCapabilitiesOneNetworkOriginsItemMax = 2048

export const canvasesPublishCreateBodyProjectOneCapabilitiesOneNetworkOriginsMax = 20

export const canvasesPublishCreateBodyNameMax = 400

export const CanvasesPublishCreateBody = /* @__PURE__ */ zod
    .object({
        project: zod
            .object({
                schemaVersion: zod.number().describe('Source-project schema version. Currently always 1.'),
                files: zod
                    .record(zod.string(), zod.string())
                    .describe("Project files keyed by relative path (forward slashes, no '..')."),
                assets: zod
                    .record(
                        zod.string(),
                        zod.object({
                            encoding: zod.enum(['base64']).describe('\* `base64` - base64'),
                            contentType: zod
                                .enum([
                                    'image/png',
                                    'image/jpeg',
                                    'image/gif',
                                    'image/webp',
                                    'image/svg+xml',
                                    'font/woff',
                                    'font/woff2',
                                    'application/wasm',
                                    'application/octet-stream',
                                ])
                                .describe(
                                    '\* `image\/png` - image\/png\n\* `image\/jpeg` - image\/jpeg\n\* `image\/gif` - image\/gif\n\* `image\/webp` - image\/webp\n\* `image\/svg+xml` - image\/svg+xml\n\* `font\/woff` - font\/woff\n\* `font\/woff2` - font\/woff2\n\* `application\/wasm` - application\/wasm\n\* `application\/octet-stream` - application\/octet-stream'
                                ),
                            content: zod
                                .string()
                                .max(canvasesPublishCreateBodyProjectOneAssetsContentMax)
                                .regex(canvasesPublishCreateBodyProjectOneAssetsContentRegExp),
                        })
                    )
                    .optional()
                    .describe('Optional base64-encoded binary assets keyed by safe project-relative paths.'),
                entryHtml: zod.string().describe('The project\'s entry HTML file. Currently always \"index.html\".'),
                dependencies: zod
                    .record(zod.string(), zod.string())
                    .optional()
                    .describe(
                        'Exact-version dependencies, restricted to the platform-supported set at its pinned versions.'
                    ),
                canvasSdkVersion: zod
                    .string()
                    .optional()
                    .describe('Version of the host-injected `ph` canvas SDK the project targets.'),
                capabilities: zod
                    .object({
                        posthog: zod.object({
                            insights: zod
                                .array(
                                    zod
                                        .string()
                                        .max(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax)
                                )
                                .max(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax),
                            inlineQueries: zod.boolean(),
                            captureEvents: zod
                                .array(
                                    zod
                                        .string()
                                        .max(
                                            canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax
                                        )
                                )
                                .max(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax),
                            state: zod
                                .array(zod.enum(['user', 'shared']).describe('\* `user` - user\n\* `shared` - shared'))
                                .max(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogStateMax)
                                .optional()
                                .describe(
                                    "State scopes the canvas may use via ph.state: 'user' (private to each viewer) and\/or 'shared' (one value per canvas, team-visible)."
                                ),
                            actions: zod
                                .array(
                                    zod
                                        .string()
                                        .max(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogActionsItemMax)
                                )
                                .max(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogActionsMax)
                                .optional()
                                .describe(
                                    "Registered action verbs the canvas may invoke via ph.actions (e.g. 'annotations.create', 'tasks.create'). Each executes as the viewer; declaring one shows it in the promote review."
                                ),
                            agentRequests: zod
                                .boolean()
                                .default(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogAgentRequestsDefault),
                        }),
                        network: zod.object({
                            origins: zod
                                .array(
                                    zod
                                        .url()
                                        .max(canvasesPublishCreateBodyProjectOneCapabilitiesOneNetworkOriginsItemMax)
                                )
                                .max(canvasesPublishCreateBodyProjectOneCapabilitiesOneNetworkOriginsMax),
                        }),
                    })
                    .optional()
                    .describe(
                        'Bounded capabilities frozen into the built artifact. Declare every insight short id the canvas loads, every event it captures, and inlineQueries when it runs ad-hoc HogQL — the host enforces these at runtime and validation rejects undeclared `ph` calls. Network origins must be exact HTTPS origins. Data fetched by canvas code can be sent to those origins.'
                    ),
            })
            .describe("A canvas's multi-file source project — the canonical write format for canvas source.")
            .describe('The complete source project to publish.'),
        prompt: zod
            .string()
            .optional()
            .describe('Short description of the change, stored on the appended version history entry.'),
        name: zod
            .string()
            .max(canvasesPublishCreateBodyNameMax)
            .optional()
            .describe('Optional new display name for the canvas.'),
        expected_current_version_id: zod
            .string()
            .nullish()
            .describe(
                'Optimistic-concurrency guard: the current_version_id the publisher based its edits on (null when it read a canvas with no versions yet). When the canvas has since moved past it the publish is rejected with a 409 version_conflict instead of overwriting the newer head. Omit to publish unguarded.'
            ),
    })
    .describe('Payload for publishing a complete canvas source project.')

/**
 * Queue a build for the current source version without changing source or metadata.
 */
export const CanvasesPublishCurrentVersionCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this canvas.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const CanvasesPublishCurrentVersionCreateBody = /* @__PURE__ */ zod.object({
    expected_current_version_id: zod
        .string()
        .describe('Current source version to publish. A changed head returns a 409 version_conflict.'),
})

/**
 * Read the canvas's source project and its `current_version_id`.
 *
 * Always call this before editing: edit the returned files, then publish
 * the complete project passing the returned version id as
 * `expected_current_version_id` so concurrent edits are not overwritten.
 * `?version_id=` reads a historical version instead of the head.
 */
export const CanvasesSourceRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this canvas.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const CanvasesSourceRetrieveQueryParams = /* @__PURE__ */ zod.object({
    version_id: zod
        .string()
        .optional()
        .describe('Read this historical source version instead of the head (for version browsing).'),
})

/**
 * Validate a candidate source project without publishing it. Side-effect free.
 */
export const CanvasesValidateCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this canvas.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const canvasesValidateCreateBodyProjectOneAssetsContentMax = 2796204

export const canvasesValidateCreateBodyProjectOneAssetsContentRegExp = new RegExp(
    '^(?:[A-Za-z0-9+\/]{4})\*(?:[A-Za-z0-9+\/]{2}==|[A-Za-z0-9+\/]{3}=)?$'
)
export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax = 128

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax = 100

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax = 200

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax = 100

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogStateMax = 2

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogActionsItemMax = 64

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogActionsMax = 32

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogAgentRequestsDefault = false
export const canvasesValidateCreateBodyProjectOneCapabilitiesOneNetworkOriginsItemMax = 2048

export const canvasesValidateCreateBodyProjectOneCapabilitiesOneNetworkOriginsMax = 20

export const CanvasesValidateCreateBody = /* @__PURE__ */ zod
    .object({
        project: zod
            .object({
                schemaVersion: zod.number().describe('Source-project schema version. Currently always 1.'),
                files: zod
                    .record(zod.string(), zod.string())
                    .describe("Project files keyed by relative path (forward slashes, no '..')."),
                assets: zod
                    .record(
                        zod.string(),
                        zod.object({
                            encoding: zod.enum(['base64']).describe('\* `base64` - base64'),
                            contentType: zod
                                .enum([
                                    'image/png',
                                    'image/jpeg',
                                    'image/gif',
                                    'image/webp',
                                    'image/svg+xml',
                                    'font/woff',
                                    'font/woff2',
                                    'application/wasm',
                                    'application/octet-stream',
                                ])
                                .describe(
                                    '\* `image\/png` - image\/png\n\* `image\/jpeg` - image\/jpeg\n\* `image\/gif` - image\/gif\n\* `image\/webp` - image\/webp\n\* `image\/svg+xml` - image\/svg+xml\n\* `font\/woff` - font\/woff\n\* `font\/woff2` - font\/woff2\n\* `application\/wasm` - application\/wasm\n\* `application\/octet-stream` - application\/octet-stream'
                                ),
                            content: zod
                                .string()
                                .max(canvasesValidateCreateBodyProjectOneAssetsContentMax)
                                .regex(canvasesValidateCreateBodyProjectOneAssetsContentRegExp),
                        })
                    )
                    .optional()
                    .describe('Optional base64-encoded binary assets keyed by safe project-relative paths.'),
                entryHtml: zod.string().describe('The project\'s entry HTML file. Currently always \"index.html\".'),
                dependencies: zod
                    .record(zod.string(), zod.string())
                    .optional()
                    .describe(
                        'Exact-version dependencies, restricted to the platform-supported set at its pinned versions.'
                    ),
                canvasSdkVersion: zod
                    .string()
                    .optional()
                    .describe('Version of the host-injected `ph` canvas SDK the project targets.'),
                capabilities: zod
                    .object({
                        posthog: zod.object({
                            insights: zod
                                .array(
                                    zod
                                        .string()
                                        .max(canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax)
                                )
                                .max(canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax),
                            inlineQueries: zod.boolean(),
                            captureEvents: zod
                                .array(
                                    zod
                                        .string()
                                        .max(
                                            canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax
                                        )
                                )
                                .max(canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax),
                            state: zod
                                .array(zod.enum(['user', 'shared']).describe('\* `user` - user\n\* `shared` - shared'))
                                .max(canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogStateMax)
                                .optional()
                                .describe(
                                    "State scopes the canvas may use via ph.state: 'user' (private to each viewer) and\/or 'shared' (one value per canvas, team-visible)."
                                ),
                            actions: zod
                                .array(
                                    zod
                                        .string()
                                        .max(canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogActionsItemMax)
                                )
                                .max(canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogActionsMax)
                                .optional()
                                .describe(
                                    "Registered action verbs the canvas may invoke via ph.actions (e.g. 'annotations.create', 'tasks.create'). Each executes as the viewer; declaring one shows it in the promote review."
                                ),
                            agentRequests: zod
                                .boolean()
                                .default(
                                    canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogAgentRequestsDefault
                                ),
                        }),
                        network: zod.object({
                            origins: zod
                                .array(
                                    zod
                                        .url()
                                        .max(canvasesValidateCreateBodyProjectOneCapabilitiesOneNetworkOriginsItemMax)
                                )
                                .max(canvasesValidateCreateBodyProjectOneCapabilitiesOneNetworkOriginsMax),
                        }),
                    })
                    .optional()
                    .describe(
                        'Bounded capabilities frozen into the built artifact. Declare every insight short id the canvas loads, every event it captures, and inlineQueries when it runs ad-hoc HogQL — the host enforces these at runtime and validation rejects undeclared `ph` calls. Network origins must be exact HTTPS origins. Data fetched by canvas code can be sent to those origins.'
                    ),
            })
            .describe("A canvas's multi-file source project — the canonical write format for canvas source.")
            .describe('The candidate source project to validate.'),
    })
    .describe('Payload for validating a candidate source project without publishing it.')
