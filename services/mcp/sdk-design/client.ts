import type { FeatureFlagsClient } from './feature-flags/client'
import type { ProjectContext, ProjectResolutionErrorDetails } from './project-context'

export type { FeatureFlagsClient } from './feature-flags/client'

export interface JsonObject {
    [key: string]: JsonValue
}

export type JsonValue = string | number | boolean | null | JsonObject | JsonValue[]

export interface PostHogClientOptions {
    /** Defaults to POSTHOG_API_URL, POSTHOG_HOST, then https://us.posthog.com. Proxy mode requires a configured URL. */
    baseUrl?: string
    /** Defaults to POSTHOG_AUTH_MODE, then token. In proxy mode, Tasks supplies authentication outside this process. */
    authMode?: 'token' | 'proxy'
    /** Defaults to POSTHOG_PERSONAL_API_KEY, then POSTHOG_API_KEY. Accepts a personal API key or OAuth token, not an ingestion key. */
    token?: string
    /** Needed for discovery only when the token format does not identify its credential family. */
    tokenType?: 'personal_api_key' | 'oauth'
    /** Defaults to POSTHOG_PROJECT_ID, then token/user discovery. Does not change the user's PostHog settings. */
    projectId?: number
    /** Defaults to POSTHOG_PUBLIC_URL, then baseUrl in token mode. Required in proxy mode for public PostHog links. */
    publicBaseUrl?: string
    /** Set false to keep an explicit client independent of process environment configuration. */
    env?: boolean
    /** Tasks may supply routing through the configured URL or a fetch implementation that uses its proxy. */
    fetch?: typeof globalThis.fetch
    timeoutMs?: number
}

export interface RequestOptions {
    signal?: AbortSignal
    /** Covers the whole call, including project discovery and any permitted retries. */
    timeoutMs?: number
}

export interface ResponseMeta {
    status: number
    requestId?: string
}

export interface ApiFieldError {
    path: (string | number)[]
    code: string
    message: string
}

export interface PostHogErrorDetails {
    kind:
        | 'configuration'
        | 'api'
        | 'input_validation'
        | 'response_validation'
        | 'transport'
        | 'timeout'
        | 'aborted'
        | 'project_resolution'
    message: string
    status?: number
    requestId?: string
    code?: string
    retryAfterMs?: number
    fields?: ApiFieldError[]
    body?: JsonValue
    projectResolution?: ProjectResolutionErrorDetails
}

export declare class PostHogError extends Error {
    readonly details: PostHogErrorDetails
}

export interface PostHogProjectClient {
    readonly projectId: number
    readonly featureFlags: FeatureFlagsClient
    context(options?: RequestOptions): Promise<ProjectContext>
}

export interface PostHogClient {
    /** Uses projectId from configuration, or lazily resolves and pins a default project. */
    readonly featureFlags: FeatureFlagsClient
    /** Resolves the default once and reports its source; subsequent calls return the same selection. */
    context(options?: RequestOptions): Promise<ProjectContext>
    /** Returns a new scope without changing any existing client's project. */
    project(projectId: number): PostHogProjectClient
}

/** Declaration for the proposed API; this design directory contains no runtime implementation. */
export declare function createPostHogClient(options?: PostHogClientOptions): PostHogClient

/** Reads environment defaults on the first API call. Importing this singleton needs no credentials or network access. */
export declare const client: PostHogClient

export default client
