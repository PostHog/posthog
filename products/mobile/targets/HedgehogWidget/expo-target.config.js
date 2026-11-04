/** @type {import('@bacons/apple-targets/app.plugin').ConfigFunction} */
module.exports = (config) => ({
    type: 'widget',
    name: 'HedgehogWidget',
    displayName: 'Hedgehog',
    // Relative to the app's bundle id, so each app variant gets its own widget id.
    bundleIdentifier: '.HedgehogWidget',
    // Interactive widgets (Button(intent:)) and animated changes between timeline entries need iOS 17.
    deploymentTarget: '17.0',
    // Values from src/ui/tokens.ts: background and orange.
    colors: {
        $widgetBackground: '#F6F6F3',
        $accent: '#F54E00',
    },
    entitlements: {
        // The App Group that app.config.ts sets for the current APP_VARIANT.
        'com.apple.security.application-groups': config.ios.entitlements['com.apple.security.application-groups'],
    },
})
