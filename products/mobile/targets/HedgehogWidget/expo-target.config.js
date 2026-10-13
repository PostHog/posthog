/** @type {import('@bacons/apple-targets/app.plugin').Config} */
module.exports = {
    type: 'widget',
    name: 'HedgehogWidget',
    displayName: 'Hedgehog',
    bundleIdentifier: '.HedgehogWidget',
    // Interactive widgets (Button(intent:)) and animated changes between timeline entries need iOS 17.
    deploymentTarget: '17.0',
    // Values from src/ui/tokens.ts: background and orange.
    colors: {
        $widgetBackground: '#F6F6F3',
        $accent: '#F54E00',
    },
    entitlements: {
        'com.apple.security.application-groups': ['group.com.posthog.code.mobile'],
    },
}
