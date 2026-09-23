#!/usr/bin/env node
// The bin. It reads the arguments, runs the command, and turns a refusal into the four fields.

import { homedir } from 'node:os'

import { WorkflowError } from '../errors.js'
import { assertProjectId } from './credentials.js'
import { runInit } from './init.js'
import { runFileCommand } from './run.js'

const USAGE = `posthog-workflows <command> <file> [options]

  init <file>      write a starter workflow file with its key filled in
  check <file>     load the file and print what a push would change. Runs without
                   credentials, and says so when it skips the comparison.
  push <file>      create or update every workflow in the file. Writes nothing when
                   nothing changed.

  --project <id>   the project to compare against or push to. Wins over
                   POSTHOG_CLI_PROJECT_ID and the credentials file.
  --host <url>     the PostHog instance. Wins over POSTHOG_CLI_HOST and the
                   credentials file.
  --force          push even when nothing changed, which is how a rotated secret lands
  --allow-move     record the new path for a file that moved`

const COMMANDS = new Set(['init', 'check', 'push'])
const FLAGS = new Set(['--force', '--allow-move'])
const OPTIONS = { '--project': 'project', '--host': 'host' } as const

interface Arguments {
    readonly command: 'init' | 'check' | 'push'
    readonly path: string
    readonly force: boolean
    readonly allowMove: boolean
    readonly project: string | undefined
    readonly host: string | undefined
}

function isOption(name: string): name is keyof typeof OPTIONS {
    return Object.hasOwn(OPTIONS, name)
}

export function parseArguments(argv: readonly string[]): Arguments {
    const positional: string[] = []
    const values: { project?: string; host?: string } = {}
    for (let index = 0; index < argv.length; index += 1) {
        const argument = argv[index] as string
        const equals = argument.startsWith('--') ? argument.indexOf('=') : -1
        const name = equals > 0 ? argument.slice(0, equals) : argument
        if (isOption(name)) {
            const inline = equals > 0 ? argument.slice(equals + 1) : undefined
            index += inline === undefined ? 1 : 0
            const value = inline ?? argv[index]
            if (value === undefined || value === '' || (inline === undefined && value.startsWith('-'))) {
                throw new WorkflowError({
                    status: 'missing_option_value',
                    message: `${name} needs a value.`,
                    why: `${name} names the ${OPTIONS[name]} outright, so it takes one right after it.`,
                    fix: `Pass the value after the option, for example ${name === '--project' ? '--project 2' : '--host https://us.posthog.com'}.`,
                })
            }
            values[OPTIONS[name]] = name === '--project' ? assertProjectId(value, '--project') : value
            continue
        }
        if (FLAGS.has(argument)) {
            continue
        }
        if (argument.startsWith('-')) {
            throw new WorkflowError({
                status: 'unknown_option',
                message: `${argument} is not an option of posthog-workflows.`,
                why: 'The CLI takes a command, a file, and the options below.',
                fix: USAGE,
            })
        }
        positional.push(argument)
    }
    const command = positional[0]
    if (command === undefined || !COMMANDS.has(command)) {
        throw new WorkflowError({
            status: 'unknown_command',
            message: command === undefined ? 'No command.' : `"${command}" is not a command of posthog-workflows.`,
            why: 'The CLI has three commands: init, check and push.',
            fix: USAGE,
        })
    }
    const path = positional[1]
    if (path === undefined) {
        throw new WorkflowError({
            status: 'missing_file',
            message: `${command} needs a file.`,
            why: 'Every command takes the path to the workflow file, so nothing is guessed from the shape of your repository.',
            fix: `Run: posthog-workflows ${command} flows/onboarding.ts`,
        })
    }
    if (positional.length > 2) {
        throw new WorkflowError({
            status: 'too_many_files',
            message: `${command} takes one file, and it was given ${positional.length - 1}.`,
            why: 'Each command reads one file, so a shell pattern that matched several would have deployed only the first one and reported success.',
            fix: `Run ${command} once for each file.`,
        })
    }
    return {
        command: command as Arguments['command'],
        path,
        force: argv.includes('--force'),
        allowMove: argv.includes('--allow-move'),
        project: values.project,
        host: values.host,
    }
}

async function main(): Promise<number> {
    const argv = process.argv.slice(2)
    const io = { out: (line: string): void => console.log(line) }
    if (argv.length === 0 || argv.includes('--help') || argv.includes('-h')) {
        io.out(USAGE)
        return 0
    }
    const parsed = parseArguments(argv)
    if (parsed.command === 'init') {
        return runInit({ path: parsed.path, cwd: process.cwd(), io })
    }
    return await runFileCommand({
        command: parsed.command,
        path: parsed.path,
        force: parsed.force,
        allowMove: parsed.allowMove,
        project: parsed.project,
        host: parsed.host,
        env: process.env,
        cwd: process.cwd(),
        homeDir: homedir(),
        io,
    })
}

/**
 * A refusal the customer's own copy of the package threw.
 *
 * `instanceof` is not enough: the file being loaded imports `@posthog/workflows` from their
 * `node_modules`, which can be a second copy of this package, and a class from another module
 * instance fails that check. The four fields are the contract, so the shape is what is read.
 *
 * @param error - Whatever the file threw while it loaded.
 */
function refusal(error: unknown): WorkflowError | null {
    if (error instanceof WorkflowError) {
        return error
    }
    const fields = (error as { fields?: Record<string, unknown> } | null)?.fields
    if (fields === undefined) {
        return null
    }
    const carries = ['status', 'message', 'why', 'fix'].every((field) => typeof fields[field] === 'string')
    return carries ? new WorkflowError(fields as unknown as WorkflowError['fields']) : null
}

try {
    process.exitCode = await main()
} catch (error) {
    const refused = refusal(error)
    if (refused === null) {
        throw error
    }
    console.error(refused.print())
    process.exitCode = 1
}
