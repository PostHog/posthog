import assert from 'node:assert/strict'
import test from 'node:test'

import {
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

const request = {
    schemaVersion: 1,
    id: 'chart-fix',
    kind: 'ota',
    runtimeVersion: '1.4.0',
    previousRelease: 'native-140',
    notes: 'Fix the chart legend.',
}
const fingerprints = { ios: 'ios-native-hash', android: 'android-native-hash' }
const previous = {
    state: 'complete',
    request: { ...request, id: 'native-140', kind: 'native', previousRelease: null },
    commit: 'a'.repeat(40),
    native: { commit: 'a'.repeat(40), runtimeVersion: '1.4.0', fingerprints },
}
const plan = {
    request,
    previous,
    appVersion: '1.4.0',
    fingerprints,
    initialRuntimeVersion: '1.3.0',
    isAncestor: () => true,
}

test('only the newly added request is selected; old requests do not get swept into a release', () => {
    assert.equal(selectRequest([{ path: 'products/mobile/src/chart.ts', status: 'M' }]), null)
    assert.equal(
        selectRequest([{ path: 'products/mobile/releases/requests/chart-fix.json', status: 'A' }]),
        'products/mobile/releases/requests/chart-fix.json'
    )
    for (const status of ['M', 'D', 'R100']) {
        assert.throws(
            () => selectRequest([{ path: 'products/mobile/releases/requests/chart-fix.json', status }]),
            /append-only/
        )
    }
    assert.throws(
        () =>
            selectRequest(
                ['one', 'two'].map((id) => ({ path: `products/mobile/releases/requests/${id}.json`, status: 'A' }))
            ),
        /Only one/
    )
})

test('malformed or ambiguous release metadata fails before any publication', () => {
    for (const invalid of [
        { ...request, id: '../production' },
        { ...request, runtimeVersion: '1.4.0-beta.1' },
        { ...request, kind: 'store-public' },
        { ...request, previousRelease: request.id },
        { ...request, channel: 'production' },
        { ...request, notes: '' },
    ]) {
        assert.throws(() => validateRequest(invalid))
    }
    assert.throws(() => validateRequest(request, 'different.json'), /filename/)
    assert.deepEqual(validateRequest(request, 'chart-fix.json'), request)
})

test('OTA requires the established runtime and matching native inputs on both platforms', () => {
    assert.doesNotThrow(() => validatePlan(plan))
    for (const platform of ['ios', 'android']) {
        assert.throws(
            () => validatePlan({ ...plan, fingerprints: { ...fingerprints, [platform]: 'new-module' } }),
            /fingerprint/
        )
    }
    assert.throws(() => validatePlan({ ...plan, appVersion: '1.5.0' }), /Request runtime/)
    assert.throws(
        () =>
            validatePlan({
                ...plan,
                previous: { ...previous, native: { ...previous.native, runtimeVersion: '1.3.0' } },
            }),
        /OTA runtime/
    )
    assert.throws(
        () => validatePlan({ ...plan, request: { ...request, previousRelease: null }, previous: null }),
        /first hosted/
    )
})

test('native releases must increase the public version, including the bootstrap release', () => {
    const native = { ...request, kind: 'native', runtimeVersion: '1.5.0' }
    assert.doesNotThrow(() => validatePlan({ ...plan, request: native, appVersion: '1.5.0' }))
    for (const version of ['1.4.0', '1.3.9']) {
        assert.throws(
            () => validatePlan({ ...plan, request: { ...native, runtimeVersion: version }, appVersion: version }),
            /increase version/
        )
    }
    assert.throws(
        () =>
            validatePlan({
                ...plan,
                request: { ...native, previousRelease: null, runtimeVersion: '1.3.0' },
                appVersion: '1.3.0',
                previous: null,
            }),
        /increase version/
    )
    assert.doesNotThrow(() =>
        validatePlan({ ...plan, request: { ...native, previousRelease: null }, appVersion: '1.5.0', previous: null })
    )
})

test('out-of-order, skipped, cancelled and unrelated predecessors never publish', () => {
    assert.throws(
        () => validatePlan({ ...plan, request: { ...request, previousRelease: 'queued-but-not-released' } }),
        /Previous release/
    )
    assert.throws(() => validatePlan({ ...plan, previous: { ...previous, state: 'claimed' } }), /not complete/)
    assert.throws(() => validatePlan({ ...plan, isAncestor: () => false }), /descend/)
})

test('native and OTA responses must include both correct platform runtimes', () => {
    const builds = ['IOS', 'ANDROID'].map((platform, i) => ({
        id: `${i}`.repeat(36),
        platform,
        status: 'FINISHED',
        distribution: 'STORE',
        appVersion: '1.4.0',
        runtime: { version: '1.4.0' },
        buildProfile: 'production',
        updateChannel: { name: 'production' },
        isForIosSimulator: false,
    }))
    const updates = ['ios', 'android'].map((platform) => ({ platform, group: 'b'.repeat(36), runtimeVersion: '1.4.0' }))
    assert.equal(validateBuilds(builds, '1.4.0').length, 2)
    assert.equal(validateUpdates(updates, '1.4.0'), 'b'.repeat(36))
    const republished = updates.map(({ platform, group, runtimeVersion }) => ({
        platform,
        group,
        runtime: { id: 'runtime-example', version: runtimeVersion },
    }))
    assert.equal(validateRepublishedUpdates(republished, '1.4.0'), 'b'.repeat(36))
    assert.throws(() => validateRepublishedUpdates(republished, '1.3.0'), /runtime differ/)
    assert.throws(() => validateRepublishedUpdates(updates, '1.4.0'), /runtime differ/)
    for (const broken of [
        builds.slice(0, 1),
        [builds[0], builds[0]],
        builds.map((build) => ({ ...build, status: 'ERRORED' })),
        builds.map((build) => ({ ...build, runtime: { version: '1.3.0' } })),
    ]) {
        assert.throws(() => validateBuilds(broken, '1.4.0'))
    }
    for (const broken of [
        updates.slice(0, 1),
        [updates[0], updates[0]],
        updates.map((update) => ({ ...update, runtimeVersion: '1.3.0' })),
    ]) {
        assert.throws(() => validateUpdates(broken, '1.4.0'))
    }
})

test('a completed rerun returns its receipt without repeating external effects', async () => {
    const existing = { state: 'complete', commit: 'c'.repeat(40), request }
    let effects = 0
    const effect = () => {
        effects++
    }
    assert.equal(
        await publishOnce({
            existing,
            commit: existing.commit,
            request,
            claim: effect,
            stage: effect,
            publish: effect,
            complete: effect,
        }),
        existing
    )
    assert.equal(effects, 0)
    await assert.rejects(() => publishOnce({ existing, commit: 'd'.repeat(40), request }), /different source/)
})

test('secret or unmaterialized native files cannot establish a compatibility baseline', () => {
    for (const variable of [
        { name: 'GOOGLE_SERVICES_JSON', type: 'FILE_BASE64', visibility: 'SECRET', valueWithFileContent: null },
        { name: 'GOOGLE_SERVICES_JSON', type: 'FILE_BASE64', visibility: 'SENSITIVE' },
        { name: 'OTHER_NATIVE_FILE', type: 'FILE_BASE64', visibility: 'SENSITIVE', valueWithFileContent: 'e30=' },
        { name: 'NATIVE_SWITCH', type: 'STRING', visibility: 'SECRET', value: null },
        { name: 'GITHUB_SHA', type: 'STRING', visibility: 'PUBLIC', value: 'fake' },
        { name: 'GH_TOKEN', type: 'STRING', visibility: 'SENSITIVE', value: 'fake' },
        { name: 'GIT_CONFIG_COUNT', type: 'STRING', visibility: 'PUBLIC', value: '0' },
        { name: 'EXPO_PUBLIC_UNSUPPORTED', type: 'STRING', visibility: 'PUBLIC', value: 'example' },
        { name: 'NODE_OPTIONS', type: 'STRING', visibility: 'PUBLIC', value: '--import=example.mjs' },
    ]) {
        assert.throws(() => validateNativeEnvironment([variable]))
    }
    assert.doesNotThrow(() =>
        validateNativeEnvironment([
            { name: 'APPLE_TEAM_ID', type: 'STRING', visibility: 'PUBLIC', value: 'EXAMPLETEAM' },
            {
                name: 'GOOGLE_SERVICES_JSON',
                type: 'FILE_BASE64',
                visibility: 'SENSITIVE',
                valueWithFileContent: 'e30=',
            },
        ])
    )
    assert.throws(
        () => validateNativeBuildFingerprints([{ platform: 'ios', fingerprint: null }], fingerprints),
        /build fingerprints differ/
    )
})

test('an interrupted publish keeps its claim and a retry cannot submit twice', async () => {
    let persisted
    let submissions = 0
    const callbacks = {
        commit: 'c'.repeat(40),
        request,
        claim: () => {
            persisted = { state: 'claimed', commit: 'c'.repeat(40), request }
        },
        stage: () => ({ builds: ['example'] }),
        publish: () => {
            submissions++
            throw new Error('connection lost after submission')
        },
        complete: () => {
            throw new Error('must not complete')
        },
    }
    await assert.rejects(() => publishOnce({ ...callbacks, existing: null }), /connection lost/)
    await assert.rejects(() => publishOnce({ ...callbacks, existing: persisted }), /already claimed/)
    assert.equal(submissions, 1)
})
