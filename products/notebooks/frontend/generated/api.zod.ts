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
    NotebookApi,
    NotebookCollabPresenceApi,
    NotebookCollabSaveApi,
    NotebookKernelConfigApi,
    NotebookMarkdownSaveApi,
    NotebookSQLV2RunRequestApi,
    PatchedNotebookApi,
} from './api.zod.schemas'

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksCreateBody = NotebookApi

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksUpdateBody = NotebookApi

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksPartialUpdateBody = PatchedNotebookApi

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksCollabMarkdownSaveCreateBody = NotebookMarkdownSaveApi

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksCollabPresenceCreateBody = NotebookCollabPresenceApi

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksCollabSaveCreateBody = NotebookCollabSaveApi

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksHogqlExecuteCreateBody = NotebookApi

/**
 * Set the notebook's kernel compute configuration. Applies at sandbox provision time: a currently running kernel keeps its resources until restarted.
 */
export const NotebooksKernelConfigCreateBody = NotebookKernelConfigApi

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksKernelExecuteCreateBody = NotebookApi

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksKernelExecuteStreamCreateBody = NotebookApi

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksKernelRestartCreateBody = NotebookApi

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksKernelStartCreateBody = NotebookApi

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const NotebooksKernelStopCreateBody = NotebookApi

/**
 * Dispatch an asynchronous run of a notebook SQL or Python cell. Returns a run_id immediately; poll the run result endpoint until the status is terminal. Flag-gated (revamped-py-notebooks).
 */
export const NotebooksSqlV2RunCreateBody = NotebookSQLV2RunRequestApi
