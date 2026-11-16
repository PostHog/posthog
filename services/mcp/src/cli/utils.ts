import * as fs from 'node:fs/promises'
import * as path from 'node:path'

import { serverDetailOf, withServerDetail } from '@/lib/errors'

export function errorCode(error: unknown): unknown {
    return typeof error === 'object' && error !== null && 'code' in error
        ? (error as { code?: unknown }).code
        : undefined
}

// Jenkins, Azure Pipelines and AWS CodeBuild don't export CI, so their own variables count too.
const CI_SERVICE_VARIABLES = [
    'GITHUB_ACTIONS',
    'GITLAB_CI',
    'CIRCLECI',
    'BUILDKITE',
    'JENKINS_URL',
    'TRAVIS',
    'BITBUCKET_COMMIT',
    'TF_BUILD',
    'CODEBUILD_BUILD_ARN',
    'TEAMCITY_VERSION',
    'DRONE',
    'SEMAPHORE',
    'APPVEYOR',
    'BITRISE_IO',
    'CM_BUILD_ID',
    'EAS_BUILD',
    'HARNESS_BUILD_ID',
    'DEPOT_JOB_URL',
    'NETLIFY',
    'CF_PAGES',
    'WORKERS_CI',
    'RENDER',
    'RAILWAY_SERVICE_ID',
    'HEROKU_TEST_RUN_ID',
    'CI_XCODE_CLOUD',
    'BUILDER_OUTPUT',
]

export function isRunningInCI(env: NodeJS.ProcessEnv): boolean {
    const ciValue = env.CI?.trim().toLowerCase()
    return (
        (ciValue !== undefined && ciValue !== '' && ciValue !== '0' && ciValue !== 'false') ||
        CI_SERVICE_VARIABLES.some((name) => env[name])
    )
}

// PostHog's reason is useful at a terminal, but it can repeat values from the request, and CI logs
// are often public. In CI the reason is left out and a note says where to see it.
export function failureText(error: unknown, isCI: boolean): string {
    const message = error instanceof Error ? error.message : String(error)
    const text =
        serverDetailOf(error) === undefined
            ? message
            : isCI
              ? `${message}\n\nPostHog's reason is hidden in CI. Run the command outside CI to see it.`
              : withServerDetail(message, error)
    // Unicode escapes keep the informational JSON valid while making terminal controls inert.
    return text.replace(/\p{Cc}/gu, (character) =>
        character === '\n' || character === '\t'
            ? character
            : `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`
    )
}

// Matches Linux's MAXSYMLINKS, so a link cycle fails instead of looping.
const MAX_SYMLINK_HOPS = 40

export function assertSafeDestination(root: string, destination: string, hint = ''): void {
    const normalizedRoot = path.resolve(root)
    const normalizedDestination = path.resolve(destination)
    if (normalizedDestination !== normalizedRoot && !normalizedDestination.startsWith(normalizedRoot + path.sep)) {
        throw new Error(`Refusing to write outside ${normalizedRoot}: ${normalizedDestination}${hint}`)
    }
}

/** Throws unless `target` stays inside `root` once symlinks are resolved, so a
 *  link committed into a checkout cannot redirect a write elsewhere. */
export async function assertResolvesInside(root: string, target: string, hint = ''): Promise<void> {
    const realRoot = await fs.realpath(root)
    const missing: string[] = []
    let existing = path.resolve(target)
    let realExisting: string
    let hops = 0
    for (;;) {
        try {
            realExisting = await fs.realpath(existing)
            break
        } catch (error) {
            if (errorCode(error) !== 'ENOENT') {
                throw error
            }
        }
        // realpath fails on a dangling link too, but writing through it creates its target.
        const isLink = await fs.lstat(existing).then(
            (stats) => stats.isSymbolicLink(),
            () => false
        )
        if (isLink) {
            hops += 1
            if (hops > MAX_SYMLINK_HOPS) {
                throw new Error(`Refusing to follow too many symlinks at ${existing}${hint}`)
            }
            // Splice the raw target on without normalizing it, so the OS resolves any `..` after
            // the links it passes through, with its own separators.
            const linkTarget = await fs.readlink(existing)
            existing = path.isAbsolute(linkTarget) ? linkTarget : `${path.dirname(existing)}${path.sep}${linkTarget}`
            continue
        }
        missing.unshift(path.basename(existing))
        existing = path.dirname(existing)
    }
    assertSafeDestination(realRoot, path.join(realExisting, ...missing), hint)
}
