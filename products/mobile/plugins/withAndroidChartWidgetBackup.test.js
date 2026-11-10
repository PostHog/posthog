const assert = require('node:assert/strict')
const { mkdtemp, mkdir, readFile, rm, writeFile } = require('node:fs/promises')
const { tmpdir } = require('node:os')
const { dirname, join, resolve } = require('node:path')

const { compileModsAsync, XML } = require('expo/config-plugins')
const withSecureStore = require('expo-secure-store/app.plugin').default

const appConfig = require('../app.config').default
const withAndroidChartWidgetBackup = require('./withAndroidChartWidgetBackup')

describe('Android chart widget backups', () => {
    test('excludes widget data from each backup transport while preserving SecureStore exclusions', async () => {
        const projectRoot = await mkdtemp(join(tmpdir(), 'posthog-widget-backup-'))
        try {
            const exp = appConfig({ config: { name: 'test', slug: 'test' }, projectRoot: resolve('.') })
            assert.ok(exp.plugins.includes('./plugins/withAndroidChartWidgetBackup'))
            const manifestPath = join(projectRoot, 'android/app/src/main/AndroidManifest.xml')
            await mkdir(dirname(manifestPath), { recursive: true })
            await writeFile(
                manifestPath,
                '<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:name=".MainApplication" /></manifest>'
            )
            await compileModsAsync(
                withAndroidChartWidgetBackup(
                    withSecureStore({ name: 'test', slug: 'test' }, { configureAndroidBackup: false })
                ),
                { projectRoot, platforms: ['android'] }
            )
            const manifest = await XML.readXMLAsync({ path: manifestPath })
            const application = manifest.manifest.application[0].$
            const readRules = async (attribute) => {
                const resource = application[attribute]
                assert.ok(resource.startsWith('@xml/chart_widget_'))
                return XML.parseXMLAsync(
                    await readFile(
                        join('modules/chart-widget/android/src/main/res/xml', `${resource.slice(5)}.xml`),
                        'utf8'
                    )
                )
            }
            const legacy = await readRules('android:fullBackupContent')
            const modern = await readRules('android:dataExtractionRules')
            for (const policy of [
                legacy['full-backup-content'],
                modern['data-extraction-rules']['cloud-backup'][0],
                modern['data-extraction-rules']['device-transfer'][0],
            ]) {
                const excluded = policy.exclude.map((entry) => entry.$)
                for (const path of ['SecureStore', 'chart_widget.xml', 'chart_widget_secure.xml']) {
                    assert.ok(excluded.some((entry) => entry.domain === 'sharedpref' && entry.path === path))
                }
                assert.ok(policy.include.some((entry) => entry.$.domain === 'sharedpref' && entry.$.path === '.'))
            }
        } finally {
            await rm(projectRoot, { recursive: true, force: true })
        }
    })
})
