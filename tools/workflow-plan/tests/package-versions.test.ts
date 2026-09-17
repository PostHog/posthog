import { execFile, execFileSync } from 'node:child_process'
import { once } from 'node:events'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import { loadWorkflow, planWorkflow } from '../src/plan.ts'
import { REPO_ROOT, pullRequest } from '../src/scenarios.ts'

const PYTHON_WORKFLOWS = ['build-hogql-parser.yml', 'build-hogql-parser-rs.yml', 'build-deltalite.yml']
const curl = execFileSync('which', ['curl'], { encoding: 'utf8' }).trim()

async function runVersionCheck(
    file: string,
    responses: (number | 'disconnect')[],
    fork = true
): Promise<{ code: number; stdout: string; requests: number; outputs: string }> {
    const workflow = loadWorkflow(path.join(REPO_ROOT, '.github/workflows', file))
    const script = workflow.jobs['check-version']?.steps?.find((step) => step.id === 'version')?.run
    if (!script) {
        throw new Error(`Missing version check in ${file}`)
    }
    const directory = mkdtempSync(path.join(tmpdir(), 'package-version-'))
    let requests = 0
    const server = createServer((request, response) => {
        const status = responses[Math.min(requests++, responses.length - 1)]!
        if (status === 'disconnect') {
            request.socket.destroy()
            return
        }
        response.writeHead(status, { Connection: 'close' })
        response.end('{}')
    })
    try {
        server.listen(0, '127.0.0.1')
        await once(server, 'listening')
        const address = server.address()
        if (!address || typeof address === 'string') {
            throw new Error('Expected a TCP address')
        }
        writeFileSync(path.join(directory, 'curl'), '#!/bin/bash\nexec "$REAL_CURL" "${@:1:$#-1}" "$TEST_PYPI_URL"\n', {
            mode: 0o755,
        })
        writeFileSync(path.join(directory, 'python'), '#!/bin/sh\necho 1.2.3\n', { mode: 0o755 })
        writeFileSync(path.join(directory, 'node'), '#!/bin/sh\nexit 0\n', { mode: 0o755 })
        const output = path.join(directory, 'output')
        const result = await new Promise<{ code: number; stdout: string }>((resolve) => {
            execFile(
                'bash',
                ['-eo', 'pipefail', '-c', script],
                {
                    cwd: REPO_ROOT,
                    env: {
                        ...process.env,
                        PATH: `${directory}:${process.env.PATH}`,
                        REAL_CURL: curl,
                        TEST_PYPI_URL: `http://127.0.0.1:${address.port}/package/json`,
                        GITHUB_OUTPUT: output,
                        GITHUB_EVENT_NAME: 'pull_request',
                        GH_TOKEN: '',
                        IS_FORK: String(fork),
                        PARSER_CHANGED: 'true',
                        DELTALITE_CHANGED: 'true',
                    },
                },
                (error, stdout) => resolve({ code: error ? 1 : 0, stdout })
            )
        })
        return { ...result, requests, outputs: existsSync(output) ? readFileSync(output, 'utf8') : '' }
    } finally {
        await new Promise<void>((resolve) => server.close(() => resolve()))
        rmSync(directory, { recursive: true, force: true })
    }
}

describe('package version checks', () => {
    it.each(PYTHON_WORKFLOWS)('%s warns forks about an unchanged published version', async (file) => {
        const fork = await runVersionCheck(file, [200])
        expect(fork.code).toBe(0)
        expect(fork.stdout).toContain('::warning::')
        expect(fork.outputs).toContain('release-needed=false')

        const sameRepository = await runVersionCheck(file, [200], false)
        expect(sameRepository.code).toBe(0)
        expect(sameRepository.stdout).not.toContain('::warning::')
    })

    it.each(PYTHON_WORKFLOWS)('%s recovers from a transient registry error', async (file) => {
        const result = await runVersionCheck(file, [503, 404])
        expect(result.code).toBe(0)
        expect(result.requests).toBe(2)
        expect(result.outputs).toContain('release-needed=true')
    })

    it.each(PYTHON_WORKFLOWS)('%s recovers from a dropped connection', async (file) => {
        const result = await runVersionCheck(file, ['disconnect', 200])
        expect(result.code).toBe(0)
        expect(result.requests).toBe(2)
        expect(result.outputs).toContain('release-needed=false')
    })

    it.each(PYTHON_WORKFLOWS)('%s fails closed on an unexpected registry response', async (file) => {
        const result = await runVersionCheck(file, [400])
        expect(result.code).toBe(1)
        expect(result.outputs).not.toContain('release-needed=true')
    })

    it.each([true, false])('npm fork warning runs only for an unchanged version (new=%s)', (isNewVersion) => {
        const workflow = loadWorkflow(path.join(REPO_ROOT, '.github/workflows/build-hogql-parser-npm.yml'))
        const plan = planWorkflow(workflow, {
            name: 'fork PR',
            github: pullRequest({ fork: true }),
            steps: {
                'check-package-version': {
                    'changed-files': { outputs: { parser_any_changed: 'true' } },
                    'check-package-version': { outputs: { 'is-new-version': String(isNewVersion) } },
                },
            },
        })
        expect(plan.errors).toEqual([])
        expect(
            plan.jobs['check-package-version']?.steps.find((step) => step.name === 'Warn fork PR if version not bumped')
                ?.runs
        ).toBe(!isNewVersion)
    })
})
