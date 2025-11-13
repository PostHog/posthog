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
 * URL to the PostHog examples markdown artifact (latest release)
 */
export const EXAMPLES_MARKDOWN_URL =
    'https://github.com/PostHog/examples/releases/latest/download/examples-mcp-resources.zip'

/**
 * Maps framework identifiers to their markdown filenames in the release artifact
 */
export const FRAMEWORK_MARKDOWN_FILES: Record<SupportedFramework, string> = {
    [SupportedFramework.NextJSApp]: 'nextjs-app-router.md',
    [SupportedFramework.NextJSPages]: 'nextjs-pages-router.md',
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
