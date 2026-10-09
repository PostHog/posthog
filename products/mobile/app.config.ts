import type { ConfigContext, ExpoConfig } from 'expo/config'

const EAS_PROJECT_ID = '4eb57b2f-79f6-4ab0-ae2c-bbd82af2cef9'
const APP_ID = 'com.posthog.code.mobile'

export default ({ config }: ConfigContext): ExpoConfig => ({
    ...config,
    name: 'PostHog',
    slug: 'posthog',
    owner: 'posthog',
    scheme: 'posthog',
    version: '1.0.0',
    orientation: 'portrait',
    userInterfaceStyle: 'light',
    icon: './assets/icon.png',
    ios: {
        bundleIdentifier: APP_ID,
        // Local device builds sign automatically with this team; EAS builds carry their own credentials.
        appleTeamId: process.env.APPLE_TEAM_ID,
        supportsTablet: false,
        infoPlist: {
            ITSAppUsesNonExemptEncryption: false,
        },
    },
    android: {
        package: APP_ID,
        adaptiveIcon: {
            foregroundImage: './assets/adaptive-icon.png',
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
                backgroundColor: '#FFFFFF',
            },
        ],
        'expo-font',
        'expo-updates',
        './plugins/withIosSceneLifecycle',
    ],
    updates: {
        url: `https://u.expo.dev/${EAS_PROJECT_ID}`,
    },
    runtimeVersion: {
        policy: 'appVersion',
    },
    extra: {
        router: {},
        eas: {
            projectId: EAS_PROJECT_ID,
        },
    },
})
