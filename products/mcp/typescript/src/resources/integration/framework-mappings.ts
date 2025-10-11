/**
 * Framework-specific mappings for documentation URLs and example projects
 */

export enum SupportedFramework {
    NextJS = 'nextjs-app-router',
}

/**
 * Maps framework identifiers to their PostHog documentation URLs
 */
export const FRAMEWORK_DOCS: Record<SupportedFramework, string> = {
    [SupportedFramework.NextJS]: 'https://posthog.com/docs/libraries/next-js.md',
}

/**
 * Maps framework identifiers to their example project repository URLs
 */
export const FRAMEWORK_EXAMPLES: Record<SupportedFramework, string> = {
    [SupportedFramework.NextJS]:
        'https://github.com/daniloc/posthog-app-router-example/archive/refs/heads/main.zip',
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
