/**
 * Framework-specific mappings for documentation URLs and example projects
 */

export enum SupportedFramework {
    NextJSApp = 'nextjs-app-router',
    NextJSPages = 'nextjs-pages-router',
}

/**
 * Maps framework identifiers to their PostHog documentation URLs
 */
export const FRAMEWORK_DOCS: Record<SupportedFramework, string> = {
    [SupportedFramework.NextJSApp]: 'https://posthog.com/docs/libraries/next-js.md',
    [SupportedFramework.NextJSPages]: 'https://posthog.com/docs/libraries/next-js.md',
}

/**
 * URL to the PostHog examples monorepo
 */
export const EXAMPLES_MONOREPO_URL =
    'https://github.com/PostHog/examples/archive/refs/heads/main.zip'

/**
 * Maps framework identifiers to their subfolder paths in the examples monorepo
 */
export const FRAMEWORK_EXAMPLE_PATHS: Record<SupportedFramework, string> = {
    [SupportedFramework.NextJSApp]: 'basics/next-app-router',
    [SupportedFramework.NextJSPages]: 'basics/next-pages-router',
}

/**
 * Check if a framework string is supported
 */
export function isSupportedFramework(framework: string): framework is SupportedFramework {
    return Object.values(SupportedFramework).includes(framework as SupportedFramework)
}

/**
 * Get the list of supported framework names
 */
export function getSupportedFrameworks(): string[] {
    return Object.values(SupportedFramework)
}

/**
 * Get a human-readable list of supported frameworks
 * @returns Comma-separated list of framework names
 */
export function getSupportedFrameworksList(): string {
    return getSupportedFrameworks().join(', ')
}
