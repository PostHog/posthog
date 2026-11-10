const REQUEST_PATH = /^products\/mobile\/releases\/requests\/([a-z0-9][a-z0-9-]{0,63})\.json$/
const ID = /^[a-z0-9][a-z0-9-]{0,63}$/
const VERSION = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/

function assert(condition, message) {
    if (!condition) {
        throw new Error(message)
    }
}

export function validateRequest(request, filename) {
    assert(request && typeof request === 'object' && !Array.isArray(request), 'Request must be a JSON object')
    const fields = ['schemaVersion', 'id', 'kind', 'runtimeVersion', 'previousRelease', 'notes']
    assert(
        Object.keys(request).length === fields.length && fields.every((key) => Object.hasOwn(request, key)),
        'Unexpected request fields'
    )
    assert(request.schemaVersion === 1, 'Unsupported release request schema')
    assert(typeof request.id === 'string' && ID.test(request.id), 'Invalid release id')
    assert(!filename || filename === `${request.id}.json`, 'Request filename must match its id')
    assert(['native', 'ota'].includes(request.kind), 'Release kind must be native or ota')
    assert(
        typeof request.runtimeVersion === 'string' && VERSION.test(request.runtimeVersion),
        'Runtime must be a stable x.y.z version'
    )
    assert(
        request.runtimeVersion.split('.').every((part) => Number.isSafeInteger(Number(part))),
        'Runtime version is too large'
    )
    assert(
        request.previousRelease === null ||
            (typeof request.previousRelease === 'string' && ID.test(request.previousRelease)),
        'Invalid previous release id'
    )
    assert(request.previousRelease !== request.id, 'A release cannot follow itself')
    assert(
        typeof request.notes === 'string' && request.notes.trim().length > 0 && request.notes.length <= 4000,
        'Release notes must contain 1–4000 characters'
    )
    return request
}

export function selectRequest(changes) {
    const requests = changes.filter(({ path }) => path.startsWith('products/mobile/releases/requests/'))
    assert(
        requests.every(({ path, status }) => REQUEST_PATH.test(path) && status === 'A'),
        'Release requests are append-only JSON files; do not edit, rename, or remove an existing request'
    )
    assert(
        requests.length <= 1,
        'Only one release request may be added in a push; split the releases into separate merges'
    )
    return requests[0]?.path ?? null
}

export function compareVersions(left, right) {
    const a = left.split('.').map(Number)
    const b = right.split('.').map(Number)
    for (let i = 0; i < 3; i++) {
        if (a[i] !== b[i]) {
            return Math.sign(a[i] - b[i])
        }
    }
    return 0
}

export function validatePlan({ request, previous, appVersion, fingerprints, initialRuntimeVersion, isAncestor }) {
    validateRequest(request)
    assert(request.runtimeVersion === appVersion, 'Request runtime must equal version in app.config.ts')
    assert(
        request.previousRelease === (previous?.request.id ?? null),
        'Previous release has not completed or production advanced; rerun the missing predecessor before this request'
    )
    if (previous) {
        assert(previous.state === 'complete', 'Previous release is not complete')
        assert(isAncestor(previous.commit), 'Release source must descend from the last completed release')
    }
    if (request.kind === 'native') {
        assert(
            compareVersions(appVersion, previous?.native.runtimeVersion ?? initialRuntimeVersion) > 0,
            'A native release must increase version in app.config.ts; build-number increments alone do not change the OTA runtime'
        )
    } else {
        assert(
            previous?.native,
            'The first hosted release must be native to establish a verified compatibility baseline'
        )
        assert(
            previous.native.runtimeVersion === appVersion,
            'OTA runtime does not match the last successful native release'
        )
        assert(
            ['ios', 'android'].every(
                (platform) =>
                    fingerprints[platform] && fingerprints[platform] === previous.native.fingerprints[platform]
            ),
            'Native fingerprint changed; request a native release with a higher app version'
        )
    }
}

export function validateBuilds(builds, runtimeVersion, appIdentifiers) {
    assert(Array.isArray(builds) && builds.length === 2, 'Expected one completed EAS build for each platform')
    assert(
        new Set(builds.map(({ platform }) => platform.toLowerCase())).size === 2,
        'Expected distinct iOS and Android builds'
    )
    return builds.map((build) => {
        const platform = build.platform.toLowerCase()
        assert(['ios', 'android'].includes(platform) && /^[a-f0-9-]{36}$/.test(build.id), 'Invalid EAS build identity')
        assert(
            build.status === 'FINISHED' && build.distribution === 'STORE',
            'Native build did not finish with store distribution'
        )
        assert(
            build.appVersion === runtimeVersion && build.runtime?.version === runtimeVersion,
            'EAS binary version/runtime differs from the validated request'
        )
        assert(
            build.buildProfile === 'production' &&
                build.updateChannel?.name === 'production' &&
                build.isForIosSimulator === false,
            'Expected a production device binary on the production channel'
        )
        assert(
            !appIdentifiers || build.appIdentifier === appIdentifiers[platform],
            'EAS binary app identity differs from the production config'
        )
        return { id: build.id, platform, status: build.status, fingerprint: build.fingerprint?.hash ?? null }
    })
}

export function validateUpdates(updates, runtimeVersion) {
    assert(Array.isArray(updates) && updates.length === 2, 'Expected an OTA update for both platforms')
    assert(new Set(updates.map(({ platform }) => platform)).size === 2, 'Expected distinct iOS and Android updates')
    const group = updates[0]?.group
    assert(typeof group === 'string' && /^[a-f0-9-]{36}$/.test(group), 'Missing EAS update group')
    assert(
        updates.every(
            (update) =>
                ['ios', 'android'].includes(update.platform) &&
                update.group === group &&
                update.runtimeVersion === runtimeVersion
        ),
        'OTA platforms, group or runtime differ from the request'
    )
    return group
}

export function validateRepublishedUpdates(updates, runtimeVersion) {
    assert(Array.isArray(updates), 'Expected raw EAS republished updates')
    return validateUpdates(
        updates.map(({ platform, group, runtime }) => ({ platform, group, runtimeVersion: runtime?.version })),
        runtimeVersion
    )
}

export function validateNativeEnvironment(variables) {
    assert(Array.isArray(variables), 'Cannot inspect the EAS production environment')
    const allowed = new Set([
        'APP_VARIANT',
        'APPLE_TEAM_ID',
        'GOOGLE_SERVICES_JSON',
        'EXPO_PUBLIC_POSTHOG_KEY',
        'EXPO_PUBLIC_POSTHOG_HOST',
        'EXPO_PUBLIC_DEMO_MODE',
        'EXPO_PUBLIC_SIGNUP_LINK',
        'EXPO_PUBLIC_OAUTH_US_CLIENT_ID',
        'EXPO_PUBLIC_OAUTH_EU_CLIENT_ID',
    ])
    for (const variable of variables) {
        assert(allowed.has(variable.name), 'EAS environment contains an unsupported app build input')
        assert(
            variable.visibility !== 'SECRET',
            'Hosted release cannot verify secret EAS environment inputs; use readable Sensitive values for native configuration and keep signing keys in EAS credentials'
        )
        assert(
            variable.type === 'STRING' || (variable.type === 'FILE_BASE64' && variable.name === 'GOOGLE_SERVICES_JSON'),
            'Unsupported native file input; only the materialized GOOGLE_SERVICES_JSON file is supported'
        )
        assert(
            typeof (variable.type === 'FILE_BASE64' ? variable.valueWithFileContent : variable.value) === 'string',
            'An EAS native input is unreadable; do not establish a partial fingerprint baseline'
        )
    }
    return variables
}

export function validateNativeBuildFingerprints(builds, fingerprints) {
    assert(
        builds.every(({ platform, fingerprint }) => fingerprint && fingerprint === fingerprints[platform]),
        'Completed EAS build fingerprints differ from the validated native inputs; reconcile the EAS environment before submitting'
    )
}

export async function publishOnce({ existing, commit, request, claim, stage, publish, complete }) {
    if (existing) {
        assert(
            existing.commit === commit && JSON.stringify(existing.request) === JSON.stringify(request),
            'Release id is already bound to different source or metadata'
        )
        assert(
            existing.state === 'complete',
            'This request was already claimed. Reconcile its EAS results and receipt before retrying; automatic retries could publish twice'
        )
        return existing
    }
    await claim()
    const staged = await stage()
    const result = await publish(staged)
    return complete(staged, result)
}
