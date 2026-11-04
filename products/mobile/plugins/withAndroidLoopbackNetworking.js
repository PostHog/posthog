const { mkdir, writeFile } = require('node:fs/promises')
const { join } = require('node:path')

const { AndroidConfig, withAndroidManifest, withDangerousMod } = require('expo/config-plugins')

module.exports = function withAndroidLoopbackNetworking(config, { allowLoopback = false } = {}) {
    config = withAndroidManifest(config, (cfg) => {
        const application = AndroidConfig.Manifest.getMainApplicationOrThrow(cfg.modResults)
        application.$['android:usesCleartextTraffic'] = 'false'
        application.$['android:networkSecurityConfig'] = '@xml/posthog_network_security_config'
        return cfg
    })

    return withDangerousMod(config, [
        'android',
        async (cfg) => {
            const resourceDir = join(cfg.modRequest.platformProjectRoot, 'app/src/main/res/xml')
            await mkdir(resourceDir, { recursive: true })
            await writeFile(
                join(resourceDir, 'posthog_network_security_config.xml'),
                `<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <base-config cleartextTrafficPermitted="false" />
    <domain-config cleartextTrafficPermitted="${allowLoopback === true}">
        <domain includeSubdomains="false">localhost</domain>
        <domain includeSubdomains="false">127.0.0.1</domain>
        <domain includeSubdomains="false">::1</domain>
    </domain-config>
</network-security-config>
`
            )
            const debugResourceDir = join(cfg.modRequest.platformProjectRoot, 'app/src/debug/res/xml')
            await mkdir(debugResourceDir, { recursive: true })
            await writeFile(
                join(debugResourceDir, 'posthog_network_security_config.xml'),
                `<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <base-config cleartextTrafficPermitted="true" />
</network-security-config>
`
            )
            return cfg
        },
    ])
}
