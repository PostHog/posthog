import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import { repositoryFromRemote, resolveSource } from '../../src/cli/source.js'

const SHA = 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'

function gitRepository(): string {
    const dir = mkdtempSync(join(tmpdir(), 'posthog-repo-'))
    const run = (...args: string[]): void => {
        const result = spawnSync('git', args, { cwd: dir, encoding: 'utf8' })
        assert.equal(result.status, 0, result.stderr)
    }
    run('init', '--initial-branch=main')
    run('config', 'user.email', 'nobody@example.com')
    run('config', 'user.name', 'Sam Example')
    run('config', 'commit.gpgsign', 'false')
    run('remote', 'add', 'origin', 'git@github.com:acme/flows.git')
    writeFileSync(join(dir, 'onboarding.ts'), '// a workflow\n')
    run('add', 'onboarding.ts')
    run('commit', '-m', 'Add the onboarding workflow')
    return dir
}

describe('source resolution', () => {
    it('takes the commit, the branch and the run from GitHub Actions', () => {
        const source = resolveSource({
            env: {
                GITHUB_ACTIONS: 'true',
                GITHUB_EVENT_NAME: 'push',
                GITHUB_SERVER_URL: 'https://github.com',
                GITHUB_REPOSITORY: 'acme/flows',
                GITHUB_SHA: SHA,
                GITHUB_REF_NAME: 'main',
                GITHUB_RUN_ID: '42',
                GITHUB_WORKSPACE: '/work',
            },
            filePath: '/work/flows/onboarding.ts',
            cwd: mkdtempSync(join(tmpdir(), 'posthog-plain-')),
        })

        assert.deepEqual(source, {
            commit: SHA,
            ref: 'main',
            repository: 'github.com/acme/flows',
            run_url: 'https://github.com/acme/flows/actions/runs/42',
            path: 'flows/onboarding.ts',
        })
    })

    it('records the branch and no commit on a pull request build', () => {
        const source = resolveSource({
            env: {
                GITHUB_ACTIONS: 'true',
                GITHUB_EVENT_NAME: 'pull_request',
                GITHUB_REPOSITORY: 'acme/flows',
                GITHUB_SHA: SHA,
                GITHUB_REF_NAME: '123/merge',
                GITHUB_HEAD_REF: 'add-onboarding',
                GITHUB_WORKSPACE: '/work',
            },
            filePath: '/work/flows/onboarding.ts',
            cwd: mkdtempSync(join(tmpdir(), 'posthog-plain-')),
        })

        assert.equal(source?.commit, undefined)
        assert.equal(source?.ref, 'add-onboarding')
    })

    it('takes the commit, the branch and the pipeline from GitLab CI', () => {
        const source = resolveSource({
            env: {
                GITLAB_CI: 'true',
                CI_SERVER_HOST: 'gitlab.com',
                CI_PROJECT_PATH: 'acme/flows',
                CI_COMMIT_SHA: SHA,
                CI_COMMIT_BRANCH: 'main',
                CI_PIPELINE_URL: 'https://gitlab.com/acme/flows/-/pipelines/7',
                CI_COMMIT_AUTHOR: 'Sam Example <sam@example.com>',
                CI_COMMIT_TITLE: 'Add the onboarding workflow',
                CI_PROJECT_DIR: '/builds/acme/flows',
            },
            filePath: '/builds/acme/flows/flows/onboarding.ts',
            cwd: mkdtempSync(join(tmpdir(), 'posthog-plain-')),
        })

        assert.deepEqual(source, {
            commit: SHA,
            ref: 'main',
            repository: 'gitlab.com/acme/flows',
            run_url: 'https://gitlab.com/acme/flows/-/pipelines/7',
            author: 'Sam Example',
            message: 'Add the onboarding workflow',
            path: 'flows/onboarding.ts',
        })
    })

    it('records no ref on a GitLab merge request pipeline', () => {
        const source = resolveSource({
            env: {
                GITLAB_CI: 'true',
                CI_SERVER_HOST: 'gitlab.com',
                CI_PROJECT_PATH: 'acme/flows',
                CI_COMMIT_SHA: SHA,
                CI_COMMIT_REF_NAME: 'refs/merge-requests/12/merge',
                CI_PROJECT_DIR: '/builds/acme/flows',
            },
            filePath: '/builds/acme/flows/flows/onboarding.ts',
            cwd: mkdtempSync(join(tmpdir(), 'posthog-plain-')),
        })

        assert.equal(source?.ref, undefined)
        assert.equal(source?.commit, SHA)
    })

    it('reads a plain checkout through git', () => {
        const dir = gitRepository()

        const source = resolveSource({ env: {}, filePath: 'onboarding.ts', cwd: dir })

        assert.match(source?.commit ?? '', /^[0-9a-f]{40}$/)
        assert.equal(source?.ref, 'main')
        assert.equal(source?.repository, 'github.com/acme/flows')
        assert.equal(source?.path, 'onboarding.ts')
        assert.equal(source?.author, 'Sam Example')
        assert.equal(source?.message, 'Add the onboarding workflow')
        assert.equal(source?.run_url, undefined)
    })

    it('resolves nothing outside a checkout and outside CI', () => {
        const source = resolveSource({
            env: {},
            filePath: 'onboarding.ts',
            cwd: mkdtempSync(join(tmpdir(), 'posthog-plain-')),
        })

        assert.equal(source, null)
    })

    it('reads a repository out of either remote form', () => {
        assert.equal(repositoryFromRemote('git@github.com:acme/flows.git'), 'github.com/acme/flows')
        assert.equal(repositoryFromRemote('https://gitlab.example.com/acme/flows'), 'gitlab.example.com/acme/flows')
    })
})
