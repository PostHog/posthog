import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import { generateKeyPairSync } from 'node:crypto'
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const scriptRoot = dirname(fileURLToPath(import.meta.url))
const require = createRequire(import.meta.url)
const { privateKey } = generateKeyPairSync('rsa', {
    modulusLength: 2048,
    privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
    publicKeyEncoding: { type: 'spki', format: 'pem' },
})

function fixture(t) {
    const temporary = mkdtempSync(join(tmpdir(), 'mobile-hosted-test-'))
    t.after(() => rmSync(temporary, { recursive: true, force: true }))
    const root = join(temporary, 'repo')
    const app = join(root, 'products/mobile')
    const scripts = join(app, 'scripts/releases')
    const requests = join(app, 'releases/requests')
    const bin = join(temporary, 'bin')
    const stateFile = join(temporary, 'state.json')
    const preload = join(temporary, 'expo-api.mjs')
    const keyPath = join(temporary, 'private-key.pem')
    writeFileSync(keyPath, privateKey, { mode: 0o600 })
    const certificate = execFileSync(
        'openssl',
        ['req', '-new', '-x509', '-key', keyPath, '-subj', '/CN=Invented mobile release test', '-days', '1'],
        { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }
    )
    writeFileSync(
        preload,
        `import {readFileSync,writeFileSync} from 'node:fs';globalThis.fetch=async()=>{const state=JSON.parse(readFileSync(process.env.MOBILE_FAKE_STATE,'utf8'));state.expoReads=(state.expoReads??0)+1;writeFileSync(process.env.MOBILE_FAKE_STATE,JSON.stringify(state));const variables=process.env.MOBILE_FAKE_SECRET==='1'?[{name:'APPLE_TEAM_ID',type:'STRING',visibility:'SECRET',value:null}]:process.env.MOBILE_FAKE_UNSUPPORTED==='1'?[{name:'UNSUPPORTED_BUILD_INPUT',type:'STRING',visibility:'PUBLIC',value:'example'}]:process.env.MOBILE_FAKE_FILE==='unreadable'?[{name:'GOOGLE_SERVICES_JSON',type:'FILE_BASE64',visibility:'SENSITIVE'}]:process.env.MOBILE_FAKE_CHANGE==='remove'&&state.expoReads===1?[{name:'EXPO_PUBLIC_POSTHOG_HOST',type:'STRING',visibility:'SENSITIVE',value:'on'}]:[];return {ok:true,json:async()=>({data:{app:{byId:{environmentVariablesIncludingSensitive:variables,ownerAccount:{environmentVariablesIncludingSensitive:[]}}}}})}}`
    )
    for (const path of [scripts, requests, bin]) {
        mkdirSync(path, { recursive: true })
    }
    for (const name of ['release.mjs', 'policy.mjs', 'receipt.mjs']) {
        copyFileSync(join(scriptRoot, name), join(scripts, name))
    }
    copyFileSync(join(scriptRoot, '../eas-build.sh'), join(app, 'scripts/eas-build.sh'))
    for (const tool of ['gh', 'eas']) {
        const source = readFileSync(join(scriptRoot, 'fixtures/hosted-cli.mjs'), 'utf8')
        writeFileSync(join(bin, tool), source, { mode: 0o755 })
    }
    const expo = join(app, 'node_modules/expo')
    for (const name of ['@expo/config', '@expo/fingerprint']) {
        mkdirSync(join(expo, 'node_modules', name), { recursive: true })
    }
    writeFileSync(join(expo, 'package.json'), '{"name":"expo","version":"57.0.0"}')
    writeFileSync(
        join(expo, 'node_modules/@expo/config/index.js'),
        `exports.getConfig=()=>({exp:{version:process.env.MOBILE_FAKE_VERSION,runtimeVersion:{policy:'appVersion'},updates:process.env.MOBILE_FAKE_SIGNING==='disabled'?{enabled:false}:{codeSigningCertificate:'./releases/ota-certificate.pem',codeSigningMetadata:{keyid:'main',alg:'rsa-v1_5-sha256'}},extra:{eas:{projectId:'example-project'}},ios:{bundleIdentifier:'com.example.ios'},android:{package:'com.example.android'}}})`
    )
    writeFileSync(
        join(expo, 'node_modules/@expo/fingerprint/index.js'),
        `exports.createFingerprintAsync=async(_root,options)=>({hash:options.platforms[0]+'-native-hash'})`
    )
    symlinkSync(dirname(require.resolve('typescript/package.json')), join(app, 'node_modules/typescript'))
    writeFileSync(join(app, 'releases/ota-certificate.pem'), certificate)
    writeFileSync(join(app, '.gitignore'), 'node_modules/\n')
    writeFileSync(join(app, 'package.json'), '{"name":"mobile-test","private":true}')
    writeFileSync(join(app, 'app.config.ts'), `export default {version:'1.3.0'}`)
    writeFileSync(
        join(app, 'releases/config.json'),
        JSON.stringify({ initialRuntimeVersion: '1.3.0', projectId: 'example-project' })
    )
    writeFileSync(
        join(app, 'eas.json'),
        JSON.stringify({
            build: {
                production: {
                    channel: 'production',
                    environment: 'production',
                    env: { APP_VARIANT: 'production', EXPO_PUBLIC_SIGNUP_LINK: '0' },
                },
            },
            submit: { production: { android: { track: 'internal' } } },
        })
    )
    writeFileSync(
        stateFile,
        JSON.stringify({
            releases: {},
            tags: {},
            pointer: null,
            deployments: [],
            deploymentStatuses: [],
            commands: [],
            submissions: [],
        })
    )
    const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: 'pipe' }).trim()
    git('init')
    git('config', 'user.name', 'Example test')
    git('config', 'user.email', 'test@example.com')
    git('config', 'commit.gpgsign', 'false')
    const commit = () => {
        git('add', '.')
        git('commit', '-m', 'test fixture')
        return git('rev-parse', 'HEAD')
    }
    commit()
    let before
    let head
    const addRequest = (id, kind, previousRelease, version = '1.4.0') => {
        before = git('rev-parse', 'HEAD')
        writeFileSync(
            join(requests, `${id}.json`),
            JSON.stringify({
                schemaVersion: 1,
                id,
                kind,
                runtimeVersion: version,
                previousRelease,
                notes: 'Invented test release.',
            })
        )
        writeFileSync(join(app, 'app.config.ts'), `export default {version:'${version}'}`)
        head = commit()
        writeFileSync(join(temporary, 'event.json'), JSON.stringify({ before, after: head }))
    }
    const invoke = (command, options = {}) =>
        spawnSync(process.execPath, [join(scripts, 'release.mjs'), ...command], {
            cwd: app,
            encoding: 'utf8',
            env: {
                ...process.env,
                NODE_OPTIONS: `--import=${preload}`,
                PATH: `${bin}:${process.env.PATH}`,
                MOBILE_FAKE_STATE: stateFile,
                MOBILE_FAKE_VERSION: '1.4.0',
                GITHUB_ACTIONS: 'true',
                GITHUB_EVENT_NAME: 'push',
                GITHUB_REPOSITORY: 'PostHog/posthog',
                GITHUB_REF: 'refs/heads/master',
                GITHUB_SHA: head,
                GITHUB_EVENT_PATH: join(temporary, 'event.json'),
                RUNNER_TEMP: temporary,
                GITHUB_STEP_SUMMARY: join(temporary, 'summary.md'),
                GITHUB_OUTPUT: join(temporary, 'output'),
                MOBILE_RELEASE_RUN_URL: 'https://example.com/run',
                MOBILE_RELEASE_BASE: '',
                MOBILE_OTA_SIGNING_KEY_PATH: keyPath,
                ...options,
            },
        })
    return {
        root,
        app,
        temporary,
        keyPath,
        stateFile,
        addRequest,
        invoke,
        git,
        state: () => JSON.parse(readFileSync(stateFile, 'utf8')),
        before: () => before,
        head: () => head,
    }
}

test('real CLI publishes readable notes and receipts, promotes an OTA from a legacy receipt and deduplicates reruns', (t) => {
    const f = fixture(t)
    f.addRequest('native-140', 'native', null)
    let outcome = f.invoke(['publish'])
    assert.equal(outcome.status, 0, outcome.stderr)
    let state = f.state()
    assert.deepEqual(state.submissions, ['1'.repeat(36), '2'.repeat(36)])
    assert.equal(state.releases['mobile-release/native-140'].draft, false)
    const native = state.releases['mobile-release/native-140']
    const nativeReceipt = JSON.parse(native.assets[0].content)
    assert.equal(nativeReceipt.state, 'complete')
    assert.deepEqual(
        nativeReceipt.result.submittedBuilds.map(({ id }) => id),
        state.submissions
    )
    assert.match(native.body, /Invented test release\./)
    assert.match(native.body, /\| iOS \| TestFlight \| Completed \|/)
    assert.match(native.body, /\| Android \| Google Play internal testing \| Completed \|/)
    assert.match(native.body, /mobile-release%2Fnative-140\/mobile-release-receipt\.json/)
    assert.doesNotMatch(native.body, /certificateFingerprint|schemaVersion/)
    assert.deepEqual(state.deploymentStatuses, ['in_progress', 'success'])
    assert.ok(state.commands.filter(({ tool }) => tool === 'eas').every(({ args }) => !args.includes('--latest')))
    const nativeEffects = state.commands.filter(({ tool }) => tool === 'eas').length
    assert.equal(f.invoke(['publish']).status, 0)
    assert.equal(f.state().commands.filter(({ tool }) => tool === 'eas').length, nativeEffects)
    native.assets[0].content = 'invalid JSON'
    writeFileSync(f.stateFile, JSON.stringify(state))
    assert.notEqual(f.invoke(['publish']).status, 0)
    assert.equal(f.state().commands.filter(({ tool }) => tool === 'eas').length, nativeEffects)
    delete native.assets
    writeFileSync(f.stateFile, JSON.stringify(state))
    assert.notEqual(f.invoke(['publish']).status, 0)
    assert.equal(f.state().commands.filter(({ tool }) => tool === 'eas').length, nativeEffects)
    native.body = JSON.stringify(nativeReceipt)
    writeFileSync(f.stateFile, JSON.stringify(state))
    f.addRequest('chart-fix', 'ota', 'native-140')
    outcome = f.invoke(['publish'])
    assert.equal(outcome.status, 0, outcome.stderr)
    state = f.state()
    const otaRelease = state.releases['mobile-release/chart-fix']
    const ota = JSON.parse(otaRelease.assets[0].content)
    assert.match(otaRelease.body, /Published to the production channel for iOS and Android\./)
    assert.doesNotMatch(otaRelease.body, /Build submissions/)
    assert.equal(ota.staged.group, 'b'.repeat(36))
    assert.equal(ota.result.productionGroup, 'c'.repeat(36))
    assert.equal(ota.native.runtimeVersion, '1.4.0')
    const promote = state.commands.find(({ command }) => command === 'update:republish')
    assert.ok(promote.args.includes('b'.repeat(36)))
    assert.ok(promote.args.includes('--destination-channel'))
    const updates = state.commands.filter(({ command }) => ['update', 'update:republish'].includes(command))
    assert.equal(updates.length, 2)
    for (const { args } of updates) {
        assert.equal(args[args.indexOf('--private-key-path') + 1], f.keyPath)
    }
    const effectsBefore = state.commands.filter(({ tool }) => tool === 'eas').length
    outcome = f.invoke(['publish'])
    assert.equal(outcome.status, 0, outcome.stderr)
    assert.equal(f.state().commands.filter(({ tool }) => tool === 'eas').length, effectsBefore)
})

test('receipt finalization failures retain the staged claim and never advance production or resubmit', async (t) => {
    for (const failure of ['receipt-upload', 'receipt-download', 'receipt-publish']) {
        await t.test(failure, (t) => {
            const f = fixture(t)
            f.addRequest('native-140', 'native', null)
            const failed = f.invoke(['publish'], { MOBILE_FAKE_FAIL: failure })
            assert.notEqual(failed.status, 0)
            const state = f.state()
            const release = state.releases['mobile-release/native-140']
            assert.equal(release.draft, true)
            const claim = JSON.parse(release.body)
            assert.equal(claim.state, 'claimed')
            assert.equal(claim.staged.builds.length, 2)
            if (failure === 'receipt-upload') {
                assert.equal(release.assets, undefined)
            } else {
                assert.equal(JSON.parse(release.assets[0].content).state, 'complete')
            }
            if (failure === 'receipt-download') {
                assert.match(failed.stderr, /Uploaded release receipt differs/)
            }
            assert.equal(state.pointer, null)
            assert.equal(state.submissions.length, 2)
            const effectsBefore = state.commands.filter(({ tool }) => tool === 'eas').length
            const retry = f.invoke(['publish'])
            assert.notEqual(retry.status, 0)
            assert.match(retry.stderr, /already claimed/)
            assert.equal(f.state().commands.filter(({ tool }) => tool === 'eas').length, effectsBefore)
            assert.equal(f.state().pointer, null)
        })
    }
})

test('lost submission response retains staged IDs and rerunning the workflow cannot duplicate submissions', (t) => {
    const f = fixture(t)
    f.addRequest('native-140', 'native', null)
    const first = f.invoke(['publish'], { MOBILE_FAKE_FAIL: 'submit' })
    assert.notEqual(first.status, 0)
    const receipt = JSON.parse(f.state().releases['mobile-release/native-140'].body)
    assert.equal(receipt.state, 'claimed')
    assert.equal(receipt.staged.builds.length, 2)
    assert.equal(f.state().pointer, null)
    const retry = f.invoke(['publish'])
    assert.notEqual(retry.status, 0)
    assert.match(retry.stderr, /already claimed/)
    assert.equal(f.state().submissions.length, 1)
    f.addRequest('native-150', 'native', null, '1.5.0')
    const bypass = f.invoke(['publish'], { MOBILE_FAKE_VERSION: '1.5.0' })
    assert.notEqual(bypass.status, 0)
    assert.match(bypass.stderr, /sharing this predecessor/)
    assert.equal(f.state().submissions.length, 1)
    assert.equal(f.state().releases['mobile-release/native-150'], undefined)
})

test('plan uses actual git additions and PR validation rejects unchanged native versions before claiming', (t) => {
    const f = fixture(t)
    f.addRequest('native-140', 'native', null, '1.3.0')
    const planned = f.invoke(['plan', '--base', f.before(), '--head', f.head()])
    assert.equal(planned.status, 0, planned.stderr)
    assert.match(readFileSync(join(f.temporary, 'output'), 'utf8'), /present=true/)
    const checked = f.invoke(['check'], { MOBILE_RELEASE_BASE: f.before(), MOBILE_FAKE_VERSION: '1.3.0' })
    assert.notEqual(checked.status, 0)
    assert.match(checked.stderr, /must increase/)
    assert.deepEqual(f.state().commands, [])
    const wrongVersion = f.invoke(['check'], { MOBILE_RELEASE_BASE: f.before(), MOBILE_FAKE_VERSION: '1.5.0' })
    assert.notEqual(wrongVersion.status, 0)
    assert.match(wrongVersion.stderr, /match the current app version/)
    assert.notEqual(f.invoke(['publish'], { GITHUB_EVENT_NAME: 'pull_request' }).status, 0)
    assert.deepEqual(f.state().commands, [])
    f.addRequest('native-corrected', 'native', null)
    const corrected = f.invoke(['publish'])
    assert.equal(corrected.status, 0, corrected.stderr)
    assert.equal(f.state().releases['mobile-release/native-140'], undefined)
    assert.equal(f.state().releases['mobile-release/native-corrected'].draft, false)
})

test('unreadable native environment inputs stop before claim and mismatched built fingerprints never submit', (t) => {
    const f = fixture(t)
    f.addRequest('native-140', 'native', null)
    for (const options of [{ MOBILE_FAKE_SECRET: '1' }, { MOBILE_FAKE_FILE: 'unreadable' }]) {
        const hidden = f.invoke(['publish'], options)
        assert.notEqual(hidden.status, 0)
        assert.match(hidden.stderr, /secret EAS environment inputs|native input is unreadable/)
        assert.deepEqual(f.state().releases, {})
        assert.equal(f.state().commands.filter(({ tool }) => tool === 'eas').length, 0)
    }
    const unsupported = f.invoke(['publish'], { MOBILE_FAKE_UNSUPPORTED: '1' })
    assert.notEqual(unsupported.status, 0)
    assert.match(unsupported.stderr, /unsupported app build input/)
    assert.deepEqual(f.state().releases, {})
    assert.equal(f.state().commands.filter(({ tool }) => tool === 'eas').length, 0)
    const mismatch = f.invoke(['publish'], { MOBILE_FAKE_FAIL: 'fingerprint' })
    assert.notEqual(mismatch.status, 0)
    assert.match(mismatch.stderr, /build fingerprints differ/)
    assert.deepEqual(f.state().submissions, [])
    assert.deepEqual(f.state().deploymentStatuses, ['in_progress', 'failure'])
})

test('removing a build-time variable during staging cannot inherit a stale value and publish', (t) => {
    const f = fixture(t)
    f.addRequest('native-140', 'native', null)
    const outcome = f.invoke(['publish'], { MOBILE_FAKE_CHANGE: 'remove' })
    assert.notEqual(outcome.status, 0)
    assert.match(outcome.stderr, /names, types or contents changed/)
    assert.deepEqual(f.state().submissions, [])
    assert.equal(f.state().pointer, null)
})

test('signing configuration and a matching private key are required before a release is claimed', (t) => {
    const f = fixture(t)
    f.addRequest('native-140', 'native', null)
    const unsigned = f.invoke(['publish'], { MOBILE_FAKE_SIGNING: 'disabled' })
    assert.notEqual(unsigned.status, 0)
    assert.match(unsigned.stderr, /pinned OTA signing certificate/)
    assert.deepEqual(f.state().releases, {})
    assert.equal(f.invoke(['publish']).status, 0)
    f.addRequest('chart-fix', 'ota', 'native-140')
    const mismatchedKey = join(f.temporary, 'mismatched-key.pem')
    writeFileSync(
        mismatchedKey,
        generateKeyPairSync('rsa', {
            modulusLength: 2048,
            privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
            publicKeyEncoding: { type: 'spki', format: 'pem' },
        }).privateKey
    )
    for (const path of ['', mismatchedKey]) {
        const outcome = f.invoke(['publish'], { MOBILE_OTA_SIGNING_KEY_PATH: path })
        assert.notEqual(outcome.status, 0)
        assert.match(outcome.stderr, /private key matching the pinned certificate/)
        assert.equal(f.state().releases['mobile-release/chart-fix'], undefined)
        assert.equal(f.state().commands.filter(({ command }) => command.startsWith('update')).length, 0)
    }
    for (const fingerprint of [undefined, 'different-certificate']) {
        const state = f.state()
        const asset = state.releases['mobile-release/native-140'].assets[0]
        const receipt = JSON.parse(asset.content)
        receipt.native.certificateFingerprint = fingerprint
        asset.content = JSON.stringify(receipt)
        writeFileSync(f.stateFile, JSON.stringify(state))
        const outcome = f.invoke(['publish'])
        assert.notEqual(outcome.status, 0)
        assert.match(outcome.stderr, /signing certificate changed; request a native release/)
        assert.equal(f.state().releases['mobile-release/chart-fix'], undefined)
    }
})
