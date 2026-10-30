const assert = require('node:assert/strict')
const { mkdtemp, mkdir, readFile, rm, writeFile } = require('node:fs/promises')
const { tmpdir } = require('node:os')
const { dirname, join, resolve } = require('node:path')

const { compileModsAsync, XML } = require('expo/config-plugins')

const appConfig = require('../app.config').default
const withAndroidLoopbackNetworking = require('./withAndroidLoopbackNetworking')

describe('Android native loopback networking', () => {
    test.each(['development', 'preview', 'production', undefined])(
        '%s generates the matching native cleartext policy',
        async (variant) => {
            const previousVariant = process.env.APP_VARIANT
            const projectRoot = await mkdtemp(join(tmpdir(), 'posthog-network-policy-'))
            try {
                if (variant === undefined) {
                    delete process.env.APP_VARIANT
                } else {
                    process.env.APP_VARIANT = variant
                }
                const exp = appConfig({ config: { name: 'test', slug: 'test' }, projectRoot: resolve('.') })
                const plugin = exp.plugins.find(
                    (entry) => Array.isArray(entry) && entry[0] === './plugins/withAndroidLoopbackNetworking'
                )
                assert.ok(plugin, 'the app must register the native network policy plugin')
                const manifestPath = join(projectRoot, 'android/app/src/main/AndroidManifest.xml')
                await mkdir(dirname(manifestPath), { recursive: true })
                await writeFile(
                    manifestPath,
                    '<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:name=".MainApplication" /></manifest>'
                )
                await compileModsAsync(withAndroidLoopbackNetworking({ name: 'test', slug: 'test' }, plugin[1]), {
                    projectRoot,
                    platforms: ['android'],
                })
                const manifest = await XML.readXMLAsync({ path: manifestPath })
                assert.equal(manifest.manifest.application[0].$['android:usesCleartextTraffic'], 'false')
                const resource = manifest.manifest.application[0].$['android:networkSecurityConfig']
                assert.equal(resource, '@xml/posthog_network_security_config')
                const policy = await XML.parseXMLAsync(
                    await readFile(
                        join(projectRoot, 'android/app/src/main/res/xml', `${resource.slice(5)}.xml`),
                        'utf8'
                    )
                )
                assert.deepEqual(policy['network-security-config'], {
                    'base-config': [{ $: { cleartextTrafficPermitted: 'false' } }],
                    'domain-config': [
                        {
                            $: {
                                cleartextTrafficPermitted: String(variant === 'development' || variant === 'preview'),
                            },
                            domain: ['localhost', '127.0.0.1', '::1'].map((host) => ({
                                _: host,
                                $: { includeSubdomains: 'false' },
                            })),
                        },
                    ],
                })
                const debugPolicy = await XML.readXMLAsync({
                    path: join(projectRoot, 'android/app/src/debug/res/xml', `${resource.slice(5)}.xml`),
                })
                assert.deepEqual(debugPolicy['network-security-config'], {
                    'base-config': [{ $: { cleartextTrafficPermitted: 'true' } }],
                })
            } finally {
                if (previousVariant === undefined) {
                    delete process.env.APP_VARIANT
                } else {
                    process.env.APP_VARIANT = previousVariant
                }
                await rm(projectRoot, { recursive: true, force: true })
            }
        }
    )
})
