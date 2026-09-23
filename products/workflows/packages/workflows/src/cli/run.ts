// The two commands that read a file: check and push. One pipeline, because check is push with
// the write taken out, and a check that took a different path would report something a push then
// contradicts.

import { WorkflowError } from '../errors.js'
import { Client } from './client.js'
import type { StoredWorkflow } from './client.js'
import { requireCredentials, resolveCredentials } from './credentials.js'
import type { Credentials } from './credentials.js'
import { diffWorkflow } from './diff.js'
import type { Change } from './diff.js'
import { loadWorkflowFile, previewEnv } from './load.js'
import type { LoadedFile, LoadedWorkflow } from './load.js'
import { resolveSource } from './source.js'
import type { Source } from './source.js'

export interface Io {
    out(line: string): void
}

export interface RunOptions {
    readonly command: 'check' | 'push'
    readonly path: string
    readonly force: boolean
    readonly allowMove: boolean
    readonly project?: string | undefined
    readonly host?: string | undefined
    readonly env: Readonly<Record<string, string | undefined>>
    readonly cwd: string
    readonly homeDir: string
    readonly io: Io
}

type Outcome = 'would create' | 'would update' | 'created' | 'updated' | 'unchanged' | 'not compared'

interface Report {
    readonly workflow: LoadedWorkflow
    readonly outcome: Outcome
    readonly changes: readonly Change[]
    readonly warnings?: readonly string[]
    readonly url?: string
    readonly version?: number
}

// `a1b2c3d on main`, or the honest shorter forms when a part did not resolve.
function describeSource(source: Source | null): string {
    if (source === null) {
        return 'not detected: this version will not name a commit'
    }
    const commit = source.commit?.slice(0, 7)
    if (commit !== undefined) {
        return source.ref === undefined ? commit : `${commit} on ${source.ref}`
    }
    const place = source.ref ?? source.repository
    return place === undefined ? 'not detected: this version will not name a commit' : `${place}, no commit recorded`
}

function printWorkflow(report: Report, source: Source | null, command: RunOptions['command'], io: Io): void {
    const { workflow } = report
    const definition = workflow.emitted.definition
    io.out(`  ${workflow.exportName} -> "${definition.name}"`)
    io.out(`    key      ${definition.key}`)
    if (definition.status !== undefined) {
        io.out(`    status   ${definition.status}`)
    }
    const types = definition.actions.map((action) => action.type)
    io.out(`    steps    ${types.length} (${types.join(', ')})`)
    for (const secret of workflow.emitted.secretInputs) {
        io.out(`    secret   ${secret.actionId}.${secret.inputKey} from $${secret.envName}, sent on every push`)
    }
    // A push that writes nothing records no version, so the commit it came from is not stored
    // either. Saying so here is cheaper than a customer looking for it later. `check` records
    // nothing either way, so the qualifier would only read as a claim about a write it never made.
    const trailer =
        command === 'push' && source !== null && report.outcome === 'unchanged' ? ' (not recorded: no change)' : ''
    io.out(`    source   ${describeSource(source)}${trailer}`)
    if (source === null) {
        io.out(
            '             fix: Run push from a git checkout, or from GitHub Actions or GitLab CI, so the version names the commit it came from.'
        )
    }
    for (const warning of report.warnings ?? []) {
        io.out(`    warning  ${warning}`)
    }
    if (report.outcome === 'not compared') {
        io.out('    diff     not compared')
    } else {
        io.out(`    result   ${report.outcome}`)
    }
    const sign = { added: '+', removed: '-', changed: '~' } as const
    for (const change of report.changes) {
        const head = `${sign[change.kind]} ${change.what}`
        io.out(`             ${change.before === undefined ? head : `${head}: ${change.before} -> ${change.after}`}`)
    }
    if (report.url !== undefined) {
        io.out(`    url      ${report.url}`)
    }
    if (report.version !== undefined) {
        io.out(`    version  ${report.version}`)
    }
}

function count(reports: readonly Report[], outcome: Outcome): number {
    return reports.filter((report) => report.outcome === outcome).length
}

function printFooter(
    options: RunOptions,
    reports: readonly Report[],
    credentials: Credentials | null,
    client: Client | null
): void {
    const { io } = options
    if (options.command === 'push') {
        io.out(
            `pushed ${reports.length} workflow(s): ${count(reports, 'created')} created, ${count(reports, 'updated')} updated, ${count(reports, 'unchanged')} unchanged.`
        )
    } else if (client !== null) {
        io.out(
            `${reports.length} workflow(s): ${count(reports, 'would create')} would be created, ${count(reports, 'would update')} would be updated, ${count(reports, 'unchanged')} unchanged.`
        )
    } else {
        io.out(`${reports.length} workflow(s), all valid.`)
    }
    if (credentials === null) {
        // A pull request from a fork cannot read a repository secret, so check has to say which
        // half ran. Without these two lines "all valid" reads as "nothing would change".
        io.out('diff skipped: no PostHog credentials in this environment, so the file was validated offline.')
        io.out(
            options.project === undefined
                ? 'Set POSTHOG_CLI_API_KEY and POSTHOG_CLI_PROJECT_ID to compare against a project.'
                : `Set POSTHOG_CLI_API_KEY to compare against project ${options.project}.`
        )
        return
    }
    const verb = options.command === 'check' ? 'compared against' : 'pushed to'
    io.out(`${verb} project ${credentials.projectId} on ${credentials.host} (credentials from ${credentials.source}).`)
}

// A file that moved is a legitimate edit; a file that was copied is an accident about to overwrite
// a live workflow. The two look identical from here, so the CLI refuses and `--allow-move` is the
// author saying which one it is.
function guardPath(remote: StoredWorkflow, source: Source | null, options: RunOptions): Change | null {
    const recorded = remote.source_path
    if (typeof recorded !== 'string' || recorded === '') {
        return null
    }
    if (source?.path === undefined) {
        // The recorded path cannot be compared with anything here, and a copy looks exactly like
        // this. The flag is how the author says the push is meant.
        if (options.allowMove) {
            return null
        }
        throw new WorkflowError({
            status: 'path_not_resolved',
            message: `The workflow "${String(remote.key ?? '')}" was last pushed from ${recorded}, and this push cannot tell which file it comes from.`,
            why: 'The file is not inside a git checkout and no CI variables name one, so the path this push comes from is unknown and a copy of the file cannot be told apart from the original.',
            fix: `Run the push from the checkout that holds ${recorded}, or run it again with --allow-move to push from here anyway.`,
        })
    }
    if (recorded === source.path) {
        return null
    }
    if (options.allowMove) {
        // The pointer is not part of the definition, so a move alone leaves the comparison empty.
        // It still has to be written, or the next push is refused for the same reason again.
        return { kind: 'changed', what: 'the recorded path', before: recorded, after: source.path }
    }
    throw new WorkflowError({
        status: 'path_mismatch',
        message: `The workflow "${String(remote.key ?? '')}" was last pushed from ${recorded}, and this push comes from ${source.path}.`,
        why: 'A file that was copied rather than moved keeps the key of the original, so this push would replace a workflow that another file still owns.',
        fix: `If ${source.path} is the same file in a new place, run the push again with --allow-move. If it is a copy, give it a key of its own.`,
    })
}

function bodyFor(workflow: LoadedWorkflow, source: Source | null, forUpdate: boolean): Record<string, unknown> {
    const definition = workflow.emitted.definition
    // PostHog refuses a key on an update, because changing one would be a workflow claiming
    // another workflow's identity.
    const { key, ...content } = definition
    const pointer =
        source === null
            ? {}
            : {
                  ...(source.repository === undefined ? {} : { source_repository: source.repository }),
                  ...(source.path === undefined ? {} : { source_path: source.path }),
                  // The pointer on the workflow is the newest push, so the sha is the better value
                  // when there is one.
                  ...((source.commit ?? source.ref) ? { source_ref: source.commit ?? source.ref } : {}),
              }
    // Sent on every write and not only on the create, so a push that changes something re-claims a
    // workflow released in the UI. An unchanged push writes nothing, so re-claiming alone takes --force.
    const ownership = { managed_by: 'code' } as const
    return forUpdate ? { ...content, ...pointer, ...ownership } : { ...content, key, ...pointer, ...ownership }
}

// Anything a push resolved from the environment, so it can be taken out of what PostHog says back.
// A validation error that quotes the value it refused would otherwise put a live credential into a
// CI log that anybody on the repository can read.
function resolvedSecrets(file: LoadedFile, env: Readonly<Record<string, string | undefined>>): string[] {
    const values = new Set<string>()
    for (const workflow of file.workflows) {
        for (const input of workflow.emitted.secretInputs) {
            const value = env[input.envName]
            if (value !== undefined && value !== '') {
                values.add(value)
            }
        }
    }
    return [...values]
}

function escapeRegExp(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// `why` and `fix` both carry text PostHog sent back, so both are scrubbed.
function redacted(error: unknown, secrets: readonly string[]): unknown {
    const fields = (error as { fields?: { why?: unknown; fix?: unknown } } | null)?.fields
    if (typeof fields?.why !== 'string' || typeof fields.fix !== 'string') {
        return error
    }
    const pattern =
        secrets.length === 0
            ? null
            : new RegExp(
                  [...secrets]
                      .sort((left, right) => right.length - left.length)
                      .map(escapeRegExp)
                      .join('|'),
                  'g'
              )
    const scrub = (text: string): string => (pattern === null ? text : text.replace(pattern, '[redacted]'))
    const why = scrub(fields.why)
    const fix = scrub(fields.fix)
    return why === fields.why && fix === fields.fix
        ? error
        : new WorkflowError({ ...(fields as WorkflowError['fields']), why, fix })
}

export async function runFileCommand(options: RunOptions): Promise<number> {
    const isPush = options.command === 'push'
    const overrides = { project: options.project, host: options.host }
    const credentials = isPush
        ? requireCredentials(options.env, options.homeDir, overrides)
        : resolveCredentials(options.env, options.homeDir, overrides)
    const client = credentials === null ? null : new Client(credentials)

    // Everything that must fail is resolved before any change is detected. An empty diff skips the
    // write, so a missing secret checked at the write would pass in silence.
    const file = await loadWorkflowFile(options.path, {
        env: isPush ? options.env : previewEnv(options.env),
    })
    const source = resolveSource({ env: options.env, filePath: options.path, cwd: options.cwd })
    const secrets = isPush ? resolvedSecrets(file, options.env) : []

    const reports: Report[] = []
    // Each workflow prints as it finishes. A file holding several of them can fail halfway, and a
    // customer who cannot see what already landed has to go and look in PostHog.
    options.io.out(file.path)
    const record = (report: Report): void => {
        reports.push(report)
        printWorkflow(report, source, options.command, options.io)
    }

    try {
        for (const workflow of file.workflows) {
            if (client === null) {
                record({ workflow, outcome: 'not compared', changes: [] })
                continue
            }
            const remote = await client.resolve(workflow.key)
            if (remote === null) {
                if (!isPush) {
                    record({ workflow, outcome: 'would create', changes: [] })
                    continue
                }
                const created = await client.create(bodyFor(workflow, source, false))
                record({
                    workflow,
                    outcome: 'created',
                    changes: [],
                    // Without the key stored, the next push cannot find this workflow again.
                    ...(created.key === undefined
                        ? {
                              warnings: [
                                  'PostHog did not store the key, so the next push cannot find this workflow. Upgrade PostHog before you push again.',
                              ],
                          }
                        : {}),
                    url: client.urlFor(created.id),
                    ...(created.version === undefined ? {} : { version: created.version }),
                })
                continue
            }

            const move = guardPath(remote, source, options)
            const compareSecretInputs = isPush
                ? workflow.emitted.secretInputs
                : workflow.emitted.secretInputs.filter((input) => {
                      const value = options.env[input.envName]
                      return value !== undefined && value !== ''
                  })
            const diff = diffWorkflow(workflow.emitted.definition, remote, workflow.emitted.secretInputs, {
                compareSecretInputs,
            })
            const changes = move === null ? diff.changes : [...diff.changes, move]
            const changed = diff.changed || move !== null

            if (!isPush) {
                record({
                    workflow,
                    outcome: changed ? 'would update' : 'unchanged',
                    changes,
                    url: client.urlFor(remote.id),
                    ...(remote.version === undefined ? {} : { version: remote.version }),
                })
                continue
            }
            if (!changed && !options.force) {
                record({
                    workflow,
                    outcome: 'unchanged',
                    changes: [],
                    url: client.urlFor(remote.id),
                    ...(remote.version === undefined ? {} : { version: remote.version }),
                })
                continue
            }
            const saved = await client.update(remote.id, bodyFor(workflow, source, true))
            record({
                workflow,
                outcome: 'updated',
                changes,
                url: client.urlFor(saved.id),
                ...(saved.version === undefined ? {} : { version: saved.version }),
            })
        }
    } catch (error) {
        throw redacted(error, secrets)
    }

    printFooter(options, reports, credentials, client)
    return 0
}
