/**
 * Fixture seeder — no LLM, no MCP. Writes the benchmark's `fixtures` block straight
 * to the PostHog API so an agent-mode run starts from the state its tasks describe.
 *
 * Run it before every agent-mode run. Without it the feature-flag tasks score tool
 * selection only: the flags they name do not exist, so the state change half of each
 * `success_criteria` cannot be judged. Run it again after a run to reset. It is
 * idempotent over the keys it owns: every flag in `fixtures.feature_flags` is rewritten
 * and every key in `fixtures.absent_feature_flags` is cleared, so those tasks start a
 * second run where they started the first.
 *
 * `flag-create-routes-to-experiment` is the exception. The agent picks the key of the
 * flag its experiment manages, so the seeder cannot name that key in
 * `absent_feature_flags`, and that task's experiment and flag accumulate across runs.
 *
 * It talks to the REST API rather than to the MCP server on purpose: the tools under
 * test must not also be the thing that builds the state they are measured against.
 *
 * Usage:
 *   LIVE_POSTHOG_URL=https://us.posthog.com LIVE_MCP_TOKEN=phx_... \
 *     pnpm exec tsx evals/runner/seed.ts [--project 12345]
 *
 * `LIVE_MCP_TOKEN` is the same personal API key the probe uses; it needs
 * `feature_flag:write`, plus `user:read` when `--project` is omitted, because the project
 * is then resolved through `/api/users/@me/`. Without `--project` the project comes from the token's current
 * project — pass it explicitly when the MCP session points somewhere else, because
 * seeding one project and scoring another looks exactly like a tool-selection
 * regression.
 *
 * Exit code is non-zero when any fixture could not be written, so CI can gate on it.
 */

import process from 'node:process'
import { parseArgs } from 'node:util'

import { type BenchmarkFlagFixture, FIXTURE_TAG, loadBenchmark } from '../benchmark/schema'

/** A flag as the list endpoint returns it, narrowed to what the seeder reads. */
interface ListedFlag {
    id: number
    key: string
}

interface SeedOutcome {
    key: string
    action: 'created' | 'updated' | 'cleared' | 'already-absent'
}

class SeedError extends Error {
    constructor(
        public readonly key: string,
        message: string
    ) {
        super(message)
        this.name = 'SeedError'
    }
}

class PostHogApi {
    constructor(
        private readonly baseUrl: string,
        private readonly token: string
    ) {}

    async request<T>(method: string, path: string, body?: unknown): Promise<T> {
        const response = await fetch(new URL(path, this.baseUrl), {
            method,
            headers: {
                Authorization: `Bearer ${this.token}`,
                ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
            },
            ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        })
        const text = await response.text()
        if (!response.ok) {
            throw new Error(`${method} ${path} → ${response.status} ${response.statusText}: ${text.slice(0, 400)}`)
        }
        return (text ? JSON.parse(text) : {}) as T
    }
}

/** The flag state a fixture declares, in the shape the feature-flags API accepts. */
function fixtureBody(fixture: BenchmarkFlagFixture): Record<string, unknown> {
    return {
        key: fixture.key,
        name: fixture.name,
        active: fixture.active,
        archived: fixture.archived,
        filters: fixture.filters,
        // A project can require a tag on every new flag, which would otherwise reject
        // the create. The tag also marks the flag as eval-owned in the flag list.
        tags: [FIXTURE_TAG],
    }
}

/**
 * The fixture flag with this key, whatever state it is in.
 *
 * Two calls because the list endpoint hides archived flags unless `archived` is passed,
 * and passing it narrows to archived flags only — neither call alone sees both.
 */
async function findFlag(api: PostHogApi, projectId: number, key: string): Promise<ListedFlag | undefined> {
    const search = `search=${encodeURIComponent(key)}`
    for (const query of [search, `${search}&archived=true`]) {
        const page = await api.request<{ results: ListedFlag[] }>(
            'GET',
            `/api/projects/${projectId}/feature_flags/?${query}`
        )
        // `search` is a substring match, so pin the exact key rather than taking the first hit.
        const exact = page.results.find((flag) => flag.key === key)
        if (exact) {
            return exact
        }
    }
    return undefined
}

async function seedFlag(api: PostHogApi, projectId: number, fixture: BenchmarkFlagFixture): Promise<SeedOutcome> {
    const existing = await findFlag(api, projectId, fixture.key)
    const body = fixtureBody(fixture)
    if (existing) {
        await api.request('PATCH', `/api/projects/${projectId}/feature_flags/${existing.id}/`, body)
        return { key: fixture.key, action: 'updated' }
    }
    await api.request('POST', `/api/projects/${projectId}/feature_flags/`, body)
    return { key: fixture.key, action: 'created' }
}

async function clearFlag(api: PostHogApi, projectId: number, key: string): Promise<SeedOutcome> {
    const existing = await findFlag(api, projectId, key)
    if (!existing) {
        return { key, action: 'already-absent' }
    }
    // Soft delete, the same write the `delete-feature-flag` tool makes.
    await api.request('PATCH', `/api/projects/${projectId}/feature_flags/${existing.id}/`, { deleted: true })
    return { key, action: 'cleared' }
}

async function resolveProjectId(api: PostHogApi, override: number | null): Promise<number> {
    if (override !== null) {
        return override
    }
    const me = await api.request<{ team?: { id?: number } }>('GET', '/api/users/@me/')
    const id = me.team?.id
    if (typeof id !== 'number') {
        throw new Error('could not resolve a current project from /api/users/@me/ — pass --project <id>')
    }
    return id
}

const PROJECT_FLAG = '--project'

/** Reads `--project <id>` or `--project=<id>`, and rejects anything else.
 *
 * Strict because this command writes. An argument it did not understand would fall
 * through to the token's current project, so a typo would seed a project nobody named.
 */
function parseProjectFlag(args: string[]): number | null {
    // `strict` rejects an unknown argument, a stray positional and a missing value, so a
    // typo stops the run instead of falling through to the token's current project. The
    // seeder writes six flags and soft-deletes one, so the wrong project is not
    // recoverable by rerunning it.
    const { values } = parseArgs({
        args,
        options: { project: { type: 'string', multiple: true } },
        strict: true,
        allowPositionals: false,
    })
    const given = values.project ?? []
    if (given.length === 0) {
        return null
    }
    if (given.length > 1) {
        throw new Error(`${PROJECT_FLAG} was given ${given.length} times`)
    }
    const id = Number(given[0])
    if (!given[0] || !Number.isInteger(id) || id <= 0) {
        throw new Error(`${PROJECT_FLAG} requires a positive integer project id`)
    }
    return id
}

async function main(): Promise<void> {
    const token = process.env.LIVE_MCP_TOKEN
    if (!token) {
        console.error(
            'LIVE_MCP_TOKEN is required (a personal API key with feature_flag:write, and user:read unless you pass --project)'
        )
        process.exit(2)
    }

    let projectOverride: number | null
    try {
        projectOverride = parseProjectFlag(process.argv.slice(2))
    } catch (error) {
        console.error(error instanceof Error ? error.message : String(error))
        process.exit(2)
        return
    }

    const api = new PostHogApi(process.env.LIVE_POSTHOG_URL ?? 'http://localhost:8000', token)
    const { fixtures } = loadBenchmark()
    const projectId = await resolveProjectId(api, projectOverride)

    const outcomes: SeedOutcome[] = []
    const failures: SeedError[] = []
    // Sequential: the fixture set is small, and one flag at a time keeps a failure
    // attributable to its own key instead of to whichever request lost a race.
    for (const fixture of fixtures.feature_flags) {
        try {
            outcomes.push(await seedFlag(api, projectId, fixture))
        } catch (error) {
            failures.push(new SeedError(fixture.key, error instanceof Error ? error.message : String(error)))
        }
    }
    for (const key of fixtures.absent_feature_flags) {
        try {
            outcomes.push(await clearFlag(api, projectId, key))
        } catch (error) {
            failures.push(new SeedError(key, error instanceof Error ? error.message : String(error)))
        }
    }

    // stdout directly: the summary IS the program output (oxlint strips console.log).
    process.stdout.write(`seeded project ${projectId}\n`)
    for (const outcome of outcomes) {
        process.stdout.write(`  ${outcome.action} ${outcome.key}\n`)
    }
    for (const failure of failures) {
        process.stdout.write(`  FAILED ${failure.key}: ${failure.message}\n`)
    }
    process.exit(failures.length > 0 ? 1 : 0)
}

void main()
