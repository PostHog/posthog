// `init` writes the one file a customer starts from, with the key already filled in, so nobody
// has to invent an identity by hand or copy the placeholder out of the documentation.

import { mkdirSync, writeFileSync } from 'node:fs'
import { basename, dirname, isAbsolute, relative, resolve } from 'node:path'

import { WorkflowError } from '../errors.js'
import type { Io } from './run.js'

// A file named after one of these would export `const class = ...`, which does not parse. The list
// matches the one PostHog uses when it renders a stored workflow as code.
const RESERVED_WORDS = new Set(
    (
        'break case catch class const continue debugger default delete do else enum export extends false ' +
        'finally for function if import in instanceof new null return super switch this throw true try ' +
        'typeof var void while with yield let static await'
    ).split(' ')
)

function words(name: string): string[] {
    return name
        .replace(/\.[^.]+$/, '')
        .replace(/\.workflow$/, '')
        .split(/[^A-Za-z0-9]+/)
        .filter((word) => word !== '')
}

function camelCase(parts: readonly string[]): string {
    return parts
        .map((word, index) => (index === 0 ? word.toLowerCase() : `${word[0]!.toUpperCase()}${word.slice(1)}`))
        .join('')
}

function sentenceCase(parts: readonly string[]): string {
    const joined = parts.join(' ').toLowerCase()
    return `${joined[0]!.toUpperCase()}${joined.slice(1)}`
}

function exportName(parts: readonly string[]): string {
    const name = camelCase(parts)
    if (!/^[A-Za-z_$]/.test(name)) {
        return `workflow${name}`
    }
    return RESERVED_WORDS.has(name) ? `${name}Workflow` : name
}

function fileExists(shown: string): WorkflowError {
    return new WorkflowError({
        status: 'file_exists',
        message: `${shown} already exists.`,
        why: 'init writes a starter workflow, and overwriting the file would throw away what is in it.',
        fix: `Pick another path, or edit ${shown} directly.`,
    })
}

function starter(exportName: string, key: string, name: string): string {
    return `import { delay, onEvent, path, workflow } from '@posthog/workflows'

export const ${exportName} = workflow({
    // The identity of this workflow in your project. Every push resolves it, so keep it as it is.
    key: '${key}',
    name: '${name}',
    // A first push sends nothing to a real person. Set this to 'active' when the workflow is ready.
    status: 'draft',
    on: onEvent({ event: 'user signed up' }),
    steps: path(delay('1d', { name: 'Wait a day' })),
    exit: { reason: '${name} finished' },
})
`
}

export function runInit(options: { path: string; cwd: string; io: Io }): number {
    const absolute = isAbsolute(options.path) ? options.path : resolve(options.cwd, options.path)
    const shown = relative(options.cwd, absolute) || options.path
    const parts = words(basename(absolute))

    if (parts.length === 0) {
        throw new WorkflowError({
            status: 'unnamed_workflow_file',
            message: `${shown} gives the workflow no name.`,
            why: 'The key and the name of the starter workflow come from the file name, and this one holds no letters or digits to take them from.',
            fix: 'Run init with a file name such as flows/onboarding.ts.',
        })
    }
    const key = parts.join('-').toLowerCase()
    const name = sentenceCase(parts)
    mkdirSync(dirname(absolute), { recursive: true })
    try {
        writeFileSync(absolute, starter(exportName(parts), key, name), { flag: 'wx' })
    } catch (error) {
        if (error instanceof Error && (error as NodeJS.ErrnoException).code === 'EEXIST') {
            throw fileExists(shown)
        }
        throw error
    }

    options.io.out(`Wrote ${shown} with the key "${key}".`)
    options.io.out(`Next: edit the steps, then run posthog-workflows check ${shown}`)
    return 0
}
