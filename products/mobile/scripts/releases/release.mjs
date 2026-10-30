import { execFileSync } from 'node:child_process'
import { createHash, createPrivateKey, X509Certificate } from 'node:crypto'
import { appendFileSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'

import {
    compareVersions,
    publishOnce,
    selectRequest,
    validateBuilds,
    validateNativeBuildFingerprints,
    validateNativeEnvironment,
    validatePlan,
    validateRepublishedUpdates,
    validateRequest,
    validateUpdates,
} from './policy.mjs'

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const repoRoot = resolve(appRoot, '../..')
const requestRoot = join(appRoot, 'releases/requests')
const config = JSON.parse(readFileSync(join(appRoot, 'releases/config.json'), 'utf8'))
const repo = 'PostHog/posthog'
const pointerRef = 'tags/mobile-production'
let releaseInventory

function run(command, args, options = {}) {
    return (
        execFileSync(command, args, {
            cwd: appRoot,
            encoding: 'utf8',
            maxBuffer: 32 * 1024 * 1024,
            stdio: ['pipe', 'pipe', 'inherit'],
            ...options,
        }) ?? ''
    ).trim()
}

function git(...args) {
    return run('git', args, { cwd: repoRoot })
}

function api(path, data, method = data ? 'POST' : 'GET') {
    const args = ['api', `repos/${repo}/${path}`, '--method', method]
    if (data) {
        args.push('--input', '-')
    }
    return JSON.parse(run('gh', args, { input: data ? JSON.stringify(data) : undefined, stdio: 'pipe' }) || 'null')
}

function optionalApi(path) {
    try {
        return api(path)
    } catch (error) {
        if (String(error.stderr).includes('HTTP 404')) {
            return null
        }
        throw new Error(`Cannot read GitHub release state: ${path}`)
    }
}

function readRequest(path) {
    return validateRequest(JSON.parse(readFileSync(path, 'utf8')), basename(path))
}

function requestFiles() {
    try {
        return readdirSync(requestRoot).filter((name) => name.endsWith('.json'))
    } catch (error) {
        if (error.code === 'ENOENT') {
            return []
        }
        throw error
    }
}

function checkRequests() {
    const requests = requestFiles().map((name) => readRequest(join(requestRoot, name)))
    const ids = new Set(requests.map(({ id }) => id))
    for (const request of requests) {
        if (request.previousRelease !== null && !ids.has(request.previousRelease)) {
            throw new Error(`Missing predecessor request ${request.previousRelease}`)
        }
        const visited = new Set([request.id])
        let previous = request.previousRelease
        while (previous !== null) {
            if (visited.has(previous)) {
                throw new Error('Release request chain contains a cycle')
            }
            visited.add(previous)
            previous = requests.find(({ id }) => id === previous).previousRelease
        }
    }
    if (process.env.MOBILE_RELEASE_BASE) {
        const path = plan(process.env.MOBILE_RELEASE_BASE, git('rev-parse', 'HEAD'))
        if (path) {
            const request = readRequest(join(repoRoot, path))
            const { exp } = expoConfig()
            if (request.runtimeVersion !== exp.version || exp.runtimeVersion?.policy !== 'appVersion') {
                throw new Error('Release request must match the current app version and appVersion runtime policy')
            }
            const require = createRequire(join(appRoot, 'package.json'))
            const ts = require('typescript')
            const source = git('show', `${process.env.MOBILE_RELEASE_BASE}:products/mobile/app.config.ts`)
            const versions = []
            const visit = (node) => {
                if (
                    ts.isPropertyAssignment(node) &&
                    node.name.getText() === 'version' &&
                    ts.isStringLiteral(node.initializer)
                ) {
                    versions.push(node.initializer.text)
                }
                ts.forEachChild(node, visit)
            }
            visit(ts.createSourceFile('app.config.ts', source, ts.ScriptTarget.Latest, true))
            if (versions.length !== 1) {
                throw new Error('The base app config must have one literal version for release comparison')
            }
            if (
                request.kind === 'native' ? compareVersions(exp.version, versions[0]) <= 0 : exp.version !== versions[0]
            ) {
                throw new Error('Native requests must increase app.config.ts version; OTA requests must retain it')
            }
        }
    }
    console.log(`Validated ${requests.length} mobile release request(s)`)
}

function plan(base, head) {
    if (!/^[a-f0-9]{40}$/.test(base ?? '') || !/^[a-f0-9]{40}$/.test(head ?? '')) {
        throw new Error('Release planning requires explicit base and head commit SHAs')
    }
    const entries = git('diff', '--name-status', '--no-renames', base, head, '--', 'products/mobile/releases/requests')
        .split('\n')
        .filter(Boolean)
    const path = selectRequest(
        entries.map((entry) => {
            const [status, changedPath] = entry.split('\t')
            return { status, path: changedPath }
        })
    )
    const request = path ? readRequest(join(repoRoot, path)) : null
    if (process.env.GITHUB_OUTPUT) {
        appendFileSync(
            process.env.GITHUB_OUTPUT,
            `present=${Boolean(path)}\nrequest=${path ?? ''}\nkind=${request?.kind ?? ''}\n`
        )
    }
    return path
}

function expoConfig() {
    process.env.APP_VARIANT = 'production'
    process.env.EXPO_PUBLIC_SIGNUP_LINK = '0'
    const require = createRequire(join(appRoot, 'package.json'))
    const expoRequire = createRequire(require.resolve('expo/package.json'))
    return { exp: expoRequire('@expo/config').getConfig(appRoot).exp, expoRequire }
}

function productionSigning(exp, kind) {
    const updates = exp.updates
    if (
        updates?.enabled === false ||
        updates?.codeSigningCertificate !== './releases/ota-certificate.pem' ||
        updates?.codeSigningMetadata?.keyid !== 'main' ||
        updates?.codeSigningMetadata?.alg !== 'rsa-v1_5-sha256'
    ) {
        throw new Error('Production releases require the pinned OTA signing certificate; see RELEASING.md')
    }
    let certificate
    try {
        certificate = new X509Certificate(readFileSync(join(appRoot, updates.codeSigningCertificate)))
    } catch {
        throw new Error('Production OTA signing certificate is missing or invalid; see RELEASING.md')
    }
    if (
        certificate.publicKey.asymmetricKeyType !== 'rsa' ||
        certificate.publicKey.asymmetricKeyDetails.modulusLength < 2048 ||
        Date.now() < Date.parse(certificate.validFrom) ||
        Date.now() >= Date.parse(certificate.validTo)
    ) {
        throw new Error('Production OTA signing certificate must be valid and contain an RSA public key')
    }
    if (kind === 'native') {
        return { privateKeyPath: null, certificateFingerprint: certificate.fingerprint256 }
    }
    const path = process.env.MOBILE_OTA_SIGNING_KEY_PATH
    try {
        if (!path || !certificate.checkPrivateKey(createPrivateKey(readFileSync(path)))) {
            throw new Error('Missing or mismatched key')
        }
    } catch {
        throw new Error('OTA release requires the private key matching the pinned certificate; see RELEASING.md')
    }
    return { privateKeyPath: path, certificateFingerprint: certificate.fingerprint256 }
}

async function nativeFingerprints(expoRequire) {
    const { createFingerprintAsync } = expoRequire('@expo/fingerprint')
    const fingerprints = {}
    for (const platform of ['ios', 'android']) {
        fingerprints[platform] = (
            await createFingerprintAsync(appRoot, {
                platforms: [platform],
                ignorePaths: ['android/**/*', 'ios/**/*'],
                silent: true,
            })
        ).hash
    }
    return fingerprints
}

async function loadProductionEnvironment() {
    const fields = 'name type visibility value valueWithFileContent: value(includeFileContent: true)'
    const response = await fetch('https://api.expo.dev/graphql', {
        method: 'POST',
        headers: { Authorization: `Bearer ${process.env.EXPO_TOKEN}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
            query: `query MobileNativeEnvironment($appId: String!, $environment: EnvironmentVariableEnvironment) { app { byId(appId: $appId) { environmentVariablesIncludingSensitive(environment: $environment) { ${fields} } ownerAccount { environmentVariablesIncludingSensitive(environment: $environment) { ${fields} linkedEnvironments(appId: $appId) } } } } }`,
            variables: { appId: config.projectId, environment: 'production' },
        }),
        signal: AbortSignal.timeout(30000),
    })
    const payload = await response.json()
    const app = payload.data?.app?.byId
    if (
        !response.ok ||
        payload.errors ||
        !app ||
        !Array.isArray(app.environmentVariablesIncludingSensitive) ||
        !Array.isArray(app.ownerAccount?.environmentVariablesIncludingSensitive)
    ) {
        throw new Error('Cannot audit the EAS production environment; no release was claimed')
    }
    const shared = app.ownerAccount.environmentVariablesIncludingSensitive.filter((variable) =>
        variable.linkedEnvironments?.includes('production')
    )
    const variables = [
        ...new Map(
            [...shared, ...app.environmentVariablesIncludingSensitive].map((variable) => [variable.name, variable])
        ).values(),
    ]
    validateNativeEnvironment(variables)
    const snapshot = variables
        .map((variable) => ({
            name: variable.name,
            type: variable.type,
            visibility: variable.visibility,
            value: variable.type === 'FILE_BASE64' ? variable.valueWithFileContent : variable.value,
        }))
        .sort((left, right) => left.name.localeCompare(right.name))
    for (const variable of variables) {
        if (variable.type === 'FILE_BASE64') {
            const path = join(appRoot, 'google-services.json')
            const contents = Buffer.from(variable.valueWithFileContent, 'base64')
            try {
                JSON.parse(contents.toString('utf8'))
            } catch {
                throw new Error('GOOGLE_SERVICES_JSON must contain valid JSON; file contents are withheld')
            }
            writeFileSync(path, contents, { mode: 0o600 })
            process.env[variable.name] = path
        } else {
            process.env[variable.name] = variable.value
        }
    }
    process.env.APP_VARIANT = 'production'
    process.env.EXPO_PUBLIC_SIGNUP_LINK = '0'
    return createHash('sha256').update(JSON.stringify(snapshot)).digest('hex')
}

function assertHosted() {
    if (
        process.env.GITHUB_ACTIONS !== 'true' ||
        process.env.GITHUB_EVENT_NAME !== 'push' ||
        process.env.GITHUB_REF !== 'refs/heads/master' ||
        process.env.GITHUB_REPOSITORY !== repo
    ) {
        throw new Error(
            'Production publishing only runs in GitHub Actions on a trusted master push. Create a release request instead'
        )
    }
    if (git('rev-parse', 'HEAD') !== process.env.GITHUB_SHA) {
        throw new Error('Checkout does not match the triggering commit')
    }
    if (git('status', '--porcelain', '--untracked-files=no')) {
        throw new Error('Publishing requires an unchanged checkout')
    }
}

function releaseTag(id) {
    return `mobile-release/${id}`
}

function releaseReceipt(id) {
    if (!releaseInventory) {
        const inventory = []
        for (let page = 1; ; page++) {
            const releases = api(`releases?per_page=100&page=${page}`)
            inventory.push(...releases.filter(({ tag_name }) => tag_name.startsWith('mobile-release/')))
            if (releases.length < 100) {
                break
            }
        }
        releaseInventory = [...new Map(inventory.map((release) => [release.id, release])).values()]
    }
    const matches = releaseInventory.filter(({ tag_name }) => tag_name === releaseTag(id))
    if (matches.length > 1) {
        throw new Error(
            `Multiple GitHub receipts for ${id}; reconcile release IDs ${matches.map(({ id }) => id).join(', ')} before retrying`
        )
    }
    const [release] = matches
    return release ? { release, receipt: JSON.parse(release.body) } : null
}

function productionState() {
    const ref = optionalApi(`git/ref/${pointerRef}`)
    if (!ref) {
        return null
    }
    if (ref.object.type !== 'tag') {
        throw new Error('Production pointer must be an annotated release receipt tag')
    }
    const tag = api(`git/tags/${ref.object.sha}`)
    const pointer = JSON.parse(tag.message)
    const state = releaseReceipt(pointer.id)
    if (
        !state ||
        state.release.draft ||
        state.receipt.state !== 'complete' ||
        state.receipt.commit !== tag.object.sha
    ) {
        throw new Error('Production pointer does not identify a completed release receipt')
    }
    return state.receipt
}

function advancePointer(receipt) {
    const current = productionState()
    if (current?.request.id === receipt.request.id) {
        return
    }
    if ((current?.request.id ?? null) !== receipt.request.previousRelease) {
        throw new Error('Production advanced after this completed release; refusing to move its pointer backwards')
    }
    const tag = api('git/tags', {
        tag: 'mobile-production',
        message: JSON.stringify({ id: receipt.request.id }),
        object: receipt.commit,
        type: 'commit',
    })
    if (current) {
        api(`git/refs/${pointerRef}`, { sha: tag.sha, force: true }, 'PATCH')
    } else {
        api('git/refs', { ref: `refs/${pointerRef}`, sha: tag.sha })
    }
}

function saveReceipt(receipt) {
    const output = join(process.env.RUNNER_TEMP, 'mobile-release-receipt.json')
    writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`)
    return output
}

function deploymentStatus(id, state) {
    api(`deployments/${id}/statuses`, { state, log_url: process.env.MOBILE_RELEASE_RUN_URL, auto_inactive: false })
}

async function publish() {
    assertHosted()
    checkRequests()
    const event = JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'))
    const requestPath = plan(event.before, process.env.GITHUB_SHA)
    if (!requestPath) {
        throw new Error('The triggering push did not add a release request')
    }
    const request = readRequest(join(repoRoot, requestPath))
    const commit = process.env.GITHUB_SHA
    const existing = releaseReceipt(request.id)
    if (
        existing?.receipt.state === 'complete' &&
        existing.receipt.commit === commit &&
        JSON.stringify(existing.receipt.request) === JSON.stringify(request)
    ) {
        const current = productionState()
        if (!current || current.request.id === request.previousRelease || current.request.id === request.id) {
            advancePointer(existing.receipt)
        }
        saveReceipt(existing.receipt)
        console.log('Release already completed; no EAS publication repeated')
        return
    }
    if (existing) {
        throw new Error(
            'Request already claimed or bound to other source. Reconcile its EAS results before retrying; see RELEASING.md'
        )
    }
    const previous = productionState()
    for (const name of requestFiles()) {
        const sibling = readRequest(join(requestRoot, name))
        if (
            sibling.id !== request.id &&
            sibling.previousRelease === request.previousRelease &&
            releaseReceipt(sibling.id)
        ) {
            throw new Error(
                'Another request sharing this predecessor already has a release receipt. Reconcile its EAS results or repair the production pointer before creating a successor'
            )
        }
    }
    const environmentSnapshot = await loadProductionEnvironment()
    const { exp, expoRequire } = expoConfig()
    if (
        exp.runtimeVersion?.policy !== 'appVersion' ||
        exp.extra?.eas?.projectId !== config.projectId ||
        exp.ios?.runtimeVersion ||
        exp.android?.runtimeVersion
    ) {
        throw new Error('Release requires the configured EAS project and one appVersion runtime for both platforms')
    }
    const { privateKeyPath, certificateFingerprint } = productionSigning(exp, request.kind)
    if (request.kind === 'ota' && previous?.native?.certificateFingerprint !== certificateFingerprint) {
        throw new Error('OTA signing certificate changed; request a native release with a higher app version')
    }
    const fingerprints = await nativeFingerprints(expoRequire)
    validatePlan({
        request,
        previous,
        appVersion: exp.version,
        fingerprints,
        initialRuntimeVersion: config.initialRuntimeVersion,
        isAncestor: (ancestor) =>
            ['ahead', 'identical'].includes(api(`compare/${ancestor}...${commit}?per_page=1`).status),
    })
    const eas = JSON.parse(readFileSync(join(appRoot, 'eas.json'), 'utf8'))
    if (
        eas.build.production.channel !== 'production' ||
        eas.build.production.environment !== 'production' ||
        eas.build.production.env.APP_VARIANT !== 'production' ||
        eas.build.production.env.EXPO_PUBLIC_SIGNUP_LINK !== '0' ||
        eas.submit.production.android.track !== 'internal'
    ) {
        throw new Error('Release profiles must target production builds and the Play internal track')
    }
    const receipt = { schemaVersion: 1, state: 'claimed', request, commit, runUrl: process.env.MOBILE_RELEASE_RUN_URL }
    const message = `mobile-release:${request.id}@${commit}`
    let deployment
    let releaseId
    try {
        await publishOnce({
            existing: null,
            commit,
            request,
            claim: () => {
                saveReceipt(receipt)
                const release = api('releases', {
                    tag_name: releaseTag(request.id),
                    target_commitish: commit,
                    draft: true,
                    prerelease: true,
                    name: `Mobile ${request.id}`,
                    body: JSON.stringify(receipt, null, 2),
                })
                releaseId = release.id
            },
            stage: async () => {
                deployment = api('deployments', {
                    ref: commit,
                    environment: 'mobile-staging',
                    auto_merge: false,
                    required_contexts: [],
                    production_environment: false,
                    description: `Stage ${request.kind} request ${request.id}`,
                })
                deploymentStatus(deployment.id, 'in_progress')
                let staged
                if (request.kind === 'native') {
                    const output = run('sh', [
                        'scripts/eas-build.sh',
                        '--profile',
                        'production',
                        '--platform',
                        'all',
                        '--non-interactive',
                        '--wait',
                        '--json',
                        '--message',
                        message,
                    ])
                    staged = {
                        builds: validateBuilds(JSON.parse(output), request.runtimeVersion, {
                            ios: exp.ios.bundleIdentifier,
                            android: exp.android.package,
                        }),
                    }
                    validateNativeBuildFingerprints(staged.builds, fingerprints)
                } else {
                    const output = run('eas', [
                        'update',
                        '--private-key-path',
                        privateKeyPath,
                        '--branch',
                        `mobile-staging-${request.id}`,
                        '--environment',
                        'production',
                        '--platform',
                        'all',
                        '--non-interactive',
                        '--json',
                        '--message',
                        message,
                    ])
                    staged = { group: validateUpdates(JSON.parse(output), request.runtimeVersion) }
                }
                if ((await loadProductionEnvironment()) !== environmentSnapshot) {
                    throw new Error(
                        'EAS environment names, types or contents changed during staging; refusing production publication'
                    )
                }
                const stagedFingerprints = await nativeFingerprints(expoRequire)
                if (['ios', 'android'].some((platform) => stagedFingerprints[platform] !== fingerprints[platform])) {
                    throw new Error('Native environment changed during staging; refusing production publication')
                }
                receipt.staged = staged
                receipt.stagingDeployment = deployment.id
                saveReceipt(receipt)
                api(
                    `releases/${releaseId}`,
                    { tag_name: releaseTag(request.id), body: JSON.stringify(receipt, null, 2) },
                    'PATCH'
                )
                deploymentStatus(deployment.id, 'success')
                return staged
            },
            publish: (staged) => {
                if (request.kind === 'native') {
                    for (const build of staged.builds) {
                        run(
                            'eas',
                            [
                                'submit',
                                '--profile',
                                'production',
                                '--platform',
                                build.platform,
                                '--id',
                                build.id,
                                '--non-interactive',
                                '--wait',
                            ],
                            { stdio: 'inherit' }
                        )
                    }
                    return { submittedBuilds: staged.builds }
                }
                const output = run('eas', [
                    'update:republish',
                    '--private-key-path',
                    privateKeyPath,
                    '--group',
                    staged.group,
                    '--destination-channel',
                    'production',
                    '--platform',
                    'all',
                    '--non-interactive',
                    '--json',
                    '--message',
                    message,
                ])
                return { productionGroup: validateRepublishedUpdates(JSON.parse(output), request.runtimeVersion) }
            },
            complete: (_staged, result) => {
                receipt.state = 'complete'
                receipt.result = result
                receipt.native =
                    request.kind === 'native'
                        ? { commit, runtimeVersion: request.runtimeVersion, fingerprints, certificateFingerprint }
                        : previous.native
                saveReceipt(receipt)
                api(
                    `releases/${releaseId}`,
                    {
                        tag_name: releaseTag(request.id),
                        draft: false,
                        prerelease: true,
                        body: JSON.stringify(receipt, null, 2),
                    },
                    'PATCH'
                )
                advancePointer(receipt)
                return receipt
            },
        })
        appendFileSync(
            process.env.GITHUB_STEP_SUMMARY,
            `Published mobile ${request.kind} request **${request.id}** from \`${commit}\`. [Receipt](https://github.com/${repo}/releases/tag/${releaseTag(request.id)})\n`
        )
    } catch (error) {
        if (deployment && !receipt.staged) {
            deploymentStatus(deployment.id, 'failure')
        }
        throw error
    }
}

async function main() {
    const { values, positionals } = parseArgs({
        allowPositionals: true,
        options: {
            id: { type: 'string' },
            previous: { type: 'string' },
            notes: { type: 'string' },
            initial: { type: 'boolean' },
            base: { type: 'string' },
            head: { type: 'string' },
        },
    })
    const [command, kind] = positionals
    if (command === 'check') {
        checkRequests()
    } else if (command === 'plan') {
        checkRequests()
        plan(values.base, values.head)
    } else if (command === 'request') {
        if (Boolean(values.initial) === Boolean(values.previous)) {
            throw new Error('Specify --initial for the first native release, or --previous <completed-request-id>')
        }
        const request = validateRequest({
            schemaVersion: 1,
            id: values.id,
            kind,
            runtimeVersion: expoConfig().exp.version,
            previousRelease: values.previous ?? null,
            notes: values.notes,
        })
        if (request.previousRelease === null && kind !== 'native') {
            throw new Error('The first hosted release must be native')
        }
        mkdirSync(requestRoot, { recursive: true })
        writeFileSync(join(requestRoot, `${request.id}.json`), `${JSON.stringify(request, null, 2)}\n`, { flag: 'wx' })
        console.log(
            `Created releases/requests/${request.id}.json; review and commit it with the app changes. No release was published`
        )
    } else if (command === 'fingerprint') {
        const { expoRequire } = expoConfig()
        console.log(JSON.stringify(await nativeFingerprints(expoRequire), null, 2))
    } else if (command === 'publish') {
        await publish()
    } else {
        throw new Error(
            'Use release:request, release:check, release:fingerprint or release:test. Publishing is hosted by Mobile Release'
        )
    }
}

main().catch((error) => {
    console.error(error.message)
    process.exitCode = 1
})
