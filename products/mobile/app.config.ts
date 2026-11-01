import { existsSync } from 'node:fs'
import { join } from 'node:path'

import type { ConfigContext, ExpoConfig } from 'expo/config'

import variantTable from './src/lib/appVariants.json'

const EAS_PROJECT_ID = '4eb57b2f-79f6-4ab0-ae2c-bbd82af2cef9'

type AppVariant = keyof typeof variantTable.variants

function isAppVariant(value: string): value is AppVariant {
    return Object.hasOwn(variantTable.variants, value)
}

// eas.json sets APP_VARIANT per build profile, and the update scripts in package.json set it per channel.
// A plain local run has none and gets the store identity; the app still treats a Metro bundle as development.
function readVariant(): AppVariant {
    const value = process.env.APP_VARIANT
    if (value === undefined || value === '') {
        return 'production'
    }
    if (!isAppVariant(value)) {
        throw new Error(`APP_VARIANT must be development, preview or production, not "${value}".`)
    }
    return value
}

// On EAS, GOOGLE_SERVICES_JSON is a file environment variable: the build gets the path of the uploaded file.
// Locally, a google-services.json next to this file is used when it exists. git and EAS both ignore it.
function googleServicesFile(projectRoot: string): string | undefined {
    if (process.env.GOOGLE_SERVICES_JSON) {
        return process.env.GOOGLE_SERVICES_JSON
    }
    return existsSync(join(projectRoot, 'google-services.json')) ? './google-services.json' : undefined
}

const ICONS: Record<AppVariant, { png: string; adaptive: string }> = {
    development: { png: './assets/icon-dev.png', adaptive: './assets/adaptive-icon-dev.png' },
    preview: { png: './assets/icon-preview.png', adaptive: './assets/adaptive-icon-preview.png' },
    production: { png: './assets/icon.png', adaptive: './assets/adaptive-icon.png' },
}

export default ({ config, projectRoot }: ConfigContext): ExpoConfig => {
    const variant = readVariant()
    const { name, idSuffix, scheme } = variantTable.variants[variant]
    const appId = `${variantTable.productionAppIds.ios}${idSuffix}`
    const androidPackage = `${variantTable.productionAppIds.android}${idSuffix}`
    // The HedgehogWidget target and both Swift readers of the shared store derive the same name from the bundle id.
    const appGroup = `group.${appId}`
    const icons = ICONS[variant]
    const otaCertificate = './releases/ota-certificate.pem'
    // Local builds work before key provisioning; the hosted publisher refuses this unsigned configuration.
    const hasOtaCertificate = existsSync(join(projectRoot, otaCertificate))

    return {
        ...config,
        name,
        slug: 'posthog',
        owner: 'posthog',
        scheme,
        version: '1.6.0',
        orientation: 'portrait',
        userInterfaceStyle: 'automatic',
        icon: icons.png,
        ios: {
            // The Icon Composer bundle draws the iOS 26 layered icon and has no badged copy, so the internal
            // variants use their PNG, which keeps their band visible on the home screen.
            icon: variant === 'production' ? './assets/app.icon' : icons.png,
            bundleIdentifier: appId,
            // Local device builds sign automatically with this team; EAS builds carry their own credentials.
            appleTeamId: process.env.APPLE_TEAM_ID,
            supportsTablet: false,
            entitlements: {
                // Shared with the HedgehogWidget extension, which reads the choreography the app writes.
                'com.apple.security.application-groups': [appGroup],
            },
            infoPlist: {
                ITSAppUsesNonExemptEncryption: false,
            },
            // Expo merges these into the template's manifest, which already declares the reasons React Native needs.
            privacyManifests: {
                NSPrivacyTracking: false,
                NSPrivacyAccessedAPITypes: [
                    {
                        NSPrivacyAccessedAPIType: 'NSPrivacyAccessedAPICategoryUserDefaults',
                        // 1C8F.1 covers the App Group suite that the widget sync writes.
                        NSPrivacyAccessedAPITypeReasons: ['CA92.1', '1C8F.1'],
                    },
                    {
                        NSPrivacyAccessedAPIType: 'NSPrivacyAccessedAPICategoryFileTimestamp',
                        NSPrivacyAccessedAPITypeReasons: ['C617.1'],
                    },
                    {
                        NSPrivacyAccessedAPIType: 'NSPrivacyAccessedAPICategorySystemBootTime',
                        NSPrivacyAccessedAPITypeReasons: ['35F9.1'],
                    },
                ],
                NSPrivacyCollectedDataTypes: [
                    collected('NSPrivacyCollectedDataTypeUserID', ['AppFunctionality', 'Analytics']),
                    collected('NSPrivacyCollectedDataTypeDeviceID', ['AppFunctionality', 'Analytics']),
                    collected('NSPrivacyCollectedDataTypeProductInteraction', ['Analytics']),
                    collected('NSPrivacyCollectedDataTypeEmailAddress', ['AppFunctionality']),
                    collected('NSPrivacyCollectedDataTypeName', ['AppFunctionality']),
                    // PostHog derives a coarse location from the request IP of each analytics event.
                    collected('NSPrivacyCollectedDataTypeCoarseLocation', ['Analytics']),
                    // Chat messages the user sends to PostHog AI.
                    collected('NSPrivacyCollectedDataTypeOtherUserContent', ['AppFunctionality']),
                    // Photos the user attaches to a PostHog AI chat.
                    collected('NSPrivacyCollectedDataTypePhotosorVideos', ['AppFunctionality']),
                ],
            },
        },
        android: {
            package: androidPackage,
            googleServicesFile: googleServicesFile(projectRoot),
            adaptiveIcon: {
                foregroundImage: icons.adaptive,
                backgroundColor: '#FFFFFF',
            },
        },
        web: {
            favicon: './assets/favicon.png',
            bundler: 'metro',
        },
        plugins: [
            'expo-router',
            'expo-secure-store',
            'expo-notifications',
            'expo-web-browser',
            [
                'expo-splash-screen',
                {
                    image: './assets/splash-icon.png',
                    imageWidth: 120,
                    resizeMode: 'contain',
                    backgroundColor: '#F6F6F3',
                    dark: {
                        image: './assets/splash-icon-dark.png',
                        backgroundColor: '#1D1F27',
                    },
                },
            ],
            'expo-font',
            'expo-updates',
            [
                'expo-image-picker',
                {
                    photosPermission: 'PostHog opens your photo library so you can attach images to PostHog AI chats.',
                    // The composer attaches from the library only.
                    cameraPermission: false,
                    microphonePermission: false,
                },
            ],
            ['./plugins/withAndroidLoopbackNetworking', { allowLoopback: variant !== 'production' }],
            './plugins/withAndroidAdaptiveIconInsets',
            './plugins/withIosSceneLifecycle',
            '@bacons/apple-targets',
        ],
        updates: {
            url: `https://u.expo.dev/${EAS_PROJECT_ID}`,
            ...(variant === 'production'
                ? hasOtaCertificate
                    ? {
                          codeSigningCertificate: otaCertificate,
                          codeSigningMetadata: { keyid: 'main', alg: 'rsa-v1_5-sha256' },
                      }
                    : { enabled: false }
                : {}),
        },
        runtimeVersion: {
            policy: 'appVersion',
        },
        extra: {
            router: {},
            appVariant: variant,
            eas: {
                projectId: EAS_PROJECT_ID,
            },
        },
    }
}

type CollectionPurpose = 'AppFunctionality' | 'Analytics'

function collected(
    type: string,
    purposes: CollectionPurpose[]
): {
    NSPrivacyCollectedDataType: string
    NSPrivacyCollectedDataTypeLinked: boolean
    NSPrivacyCollectedDataTypeTracking: boolean
    NSPrivacyCollectedDataTypePurposes: string[]
} {
    return {
        NSPrivacyCollectedDataType: type,
        NSPrivacyCollectedDataTypeLinked: true,
        NSPrivacyCollectedDataTypeTracking: false,
        NSPrivacyCollectedDataTypePurposes: purposes.map((purpose) => `NSPrivacyCollectedDataTypePurpose${purpose}`),
    }
}
