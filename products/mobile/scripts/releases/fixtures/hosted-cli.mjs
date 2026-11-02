#!/usr/bin/env node
import { createPrivateKey, sign, verify, X509Certificate } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { basename } from 'node:path'

const [command, ...args] = process.argv.slice(2)
const state = JSON.parse(readFileSync(process.env.MOBILE_FAKE_STATE, 'utf8'))
const tool = basename(process.argv[1])
state.commands.push({ tool, command, args })
function done(value = '') {
    writeFileSync(process.env.MOBILE_FAKE_STATE, JSON.stringify(state))
    console.log(typeof value === 'string' ? value : JSON.stringify(value))
}
function flag(name) {
    return args[args.indexOf(name) + 1]
}
function releases() {
    return [...Object.values(state.releases), ...(state.extraReleases ?? [])]
}
function createRelease(data) {
    const release = { ...data, id: Math.max(0, ...releases().map(({ id }) => id)) + 1 }
    if (state.releases[data.tag_name]) {
        state.extraReleases ??= []
        state.extraReleases.push(release)
    } else {
        state.releases[data.tag_name] = release
    }
    return release
}
if (tool === 'eas') {
    if (command === 'build') {
        done(
            ['IOS', 'ANDROID'].map((platform, index) => ({
                id: `${index + 1}`.repeat(36),
                platform,
                status: 'FINISHED',
                distribution: 'STORE',
                appVersion: process.env.MOBILE_FAKE_VERSION,
                runtime: { version: process.env.MOBILE_FAKE_VERSION },
                buildProfile: 'production',
                updateChannel: { name: 'production' },
                isForIosSimulator: false,
                appIdentifier: platform === 'IOS' ? 'com.example.ios' : 'com.example.android',
                fingerprint: {
                    hash:
                        process.env.MOBILE_FAKE_FAIL === 'fingerprint'
                            ? 'different-native-build'
                            : `${platform.toLowerCase()}-native-hash`,
                },
            }))
        )
    } else if (command === 'submit') {
        state.submissions.push(flag('--id'))
        done()
        if (process.env.MOBILE_FAKE_FAIL === 'submit') {
            process.exit(1)
        }
    } else if (command === 'update' || command === 'update:republish') {
        // Model the EAS signing boundary: both new manifests and republished
        // manifests must be signed by the key pinned in the installed binary.
        if (!args.includes('--private-key-path')) {
            throw new Error('An OTA manifest cannot be published without its signing key')
        }
        const key = createPrivateKey(readFileSync(flag('--private-key-path')))
        const certificate = new X509Certificate(readFileSync('releases/ota-certificate.pem'))
        const manifest = Buffer.from(JSON.stringify({ command, runtimeVersion: process.env.MOBILE_FAKE_VERSION }))
        if (!verify('sha256', manifest, certificate.publicKey, sign('sha256', manifest, key))) {
            throw new Error('The OTA signature does not match the binary certificate')
        }
        done(
            ['ios', 'android'].map((platform) => ({
                id: 'a'.repeat(36),
                group: (command === 'update' ? 'b' : 'c').repeat(36),
                platform,
                ...(command === 'update'
                    ? { runtimeVersion: process.env.MOBILE_FAKE_VERSION }
                    : { runtime: { id: 'runtime-example', version: process.env.MOBILE_FAKE_VERSION } }),
            }))
        )
    } else {
        throw new Error(`Unexpected EAS command ${command}`)
    }
} else if (command === 'release') {
    const [operation, tag] = args
    if (operation === 'create') {
        createRelease({ tag_name: tag, draft: true, body: readFileSync(flag('--notes-file'), 'utf8') })
    } else if (operation === 'edit') {
        state.releases[tag].body = readFileSync(flag('--notes-file'), 'utf8')
        if (args.includes('--draft=false')) {
            state.releases[tag].draft = false
        }
    } else {
        throw new Error(`Unexpected release operation ${operation}`)
    }
    done()
} else if (command === 'api') {
    const path = args[0].replace('repos/PostHog/posthog/', '')
    const method = flag('--method')
    const data = args.includes('--input') ? JSON.parse(readFileSync(0, 'utf8')) : null
    if (method === 'GET') {
        let value
        if (path.startsWith('releases/tags/')) {
            const tag = decodeURIComponent(path.slice('releases/tags/'.length))
            value = releases().find((release) => release.tag_name === tag && !release.draft)
        } else if (path.startsWith('releases?')) {
            const search = new URLSearchParams(path.split('?')[1])
            const page = Number(search.get('page'))
            const perPage = Number(search.get('per_page'))
            value = releases()
                .sort((left, right) => right.id - left.id)
                .slice((page - 1) * perPage, page * perPage)
        } else if (path.startsWith('releases/')) {
            value = releases().find(({ id }) => id === Number(path.split('/')[1]))
        } else if (path.startsWith('git/ref/')) {
            value = state.pointer ? { object: { type: 'tag', sha: state.pointer } } : null
        } else if (path.startsWith('git/tags/')) {
            value = state.tags[path.slice('git/tags/'.length)]
        } else if (path.startsWith('compare/')) {
            value = { status: 'ahead' }
        } else {
            throw new Error(`Unexpected API read ${path}`)
        }
        if (!value) {
            writeFileSync(process.env.MOBILE_FAKE_STATE, JSON.stringify(state))
            console.error('HTTP 404')
            process.exit(1)
        }
        done(value)
    } else if (path === 'releases' && method === 'POST') {
        done(createRelease(data))
    } else if (path.startsWith('releases/') && method === 'PATCH') {
        const release = releases().find(({ id }) => id === Number(path.split('/')[1]))
        if (!release) {
            throw new Error('Release ID not found')
        }
        if (release.draft && !data.tag_name) {
            release.tag_name = `untagged-${release.id}`
        }
        Object.assign(release, data)
        done(release)
    } else if (path === 'deployments') {
        const id = state.deployments.length + 1
        state.deployments.push({ ...data, id })
        done({ id })
    } else if (path.startsWith('deployments/')) {
        state.deploymentStatuses.push(data.state)
        done({ id: 1 })
    } else if (path === 'git/tags') {
        const sha = String(Object.keys(state.tags).length + 1).repeat(40)
        state.tags[sha] = { message: data.message, object: { sha: data.object } }
        done({ sha })
    } else if (path.startsWith('git/refs')) {
        state.pointer = data.sha
        done({})
    } else {
        throw new Error(`Unexpected API mutation ${path}`)
    }
} else {
    throw new Error(`Unexpected tool ${tool} command ${command}`)
}
