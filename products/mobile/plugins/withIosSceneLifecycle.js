// Apps built with the iOS 27 SDK do not launch unless they adopt the UIScene life cycle.
// The Expo SDK 57 prebuild template predates that rule; the SDK 58 template follows it.
// This plugin applies the SDK 58 template's three changes on top of SDK 57, using the
// ExpoAppSceneDelegate that expo 57.0.26 already ships. Remove it when the app moves to SDK 58.
const { IOSConfig, withAppDelegate, withInfoPlist } = require('expo/config-plugins')

const SCENE_DELEGATE = `internal import Expo

@objc(SceneDelegate)
class SceneDelegate: ExpoAppSceneDelegate {}
`

const CLASS_LINE = 'class AppDelegate: ExpoAppDelegate {'
const PROVIDER_CLASS_LINE = 'class AppDelegate: ExpoAppDelegate, ExpoReactNativeFactoryProvider {'
// The scene delegate creates the window and starts React Native, so the app delegate must not.
const WINDOW_BLOCK =
    /\n#if os\(iOS\) \|\| os\(tvOS\)\n\s*window = UIWindow\(frame: UIScreen\.main\.bounds\)\n\s*factory\.startReactNative\([^)]*\)\n#endif\n/

function withSceneManifest(config) {
    return withInfoPlist(config, (cfg) => {
        cfg.modResults.UIApplicationSceneManifest = {
            UIApplicationSupportsMultipleScenes: false,
            UISceneConfigurations: {
                UIWindowSceneSessionRoleApplication: [
                    {
                        UISceneConfigurationName: 'Default Configuration',
                        UISceneDelegateClassName: '$(PRODUCT_MODULE_NAME).SceneDelegate',
                    },
                ],
            },
        }
        return cfg
    })
}

function withFactoryProviderAppDelegate(config) {
    return withAppDelegate(config, (cfg) => {
        let contents = cfg.modResults.contents.replace(CLASS_LINE, PROVIDER_CLASS_LINE)
        contents = contents.replace(WINDOW_BLOCK, '\n')
        // Fail the prebuild loudly if the template changes shape, instead of shipping an app that does not launch.
        if (!contents.includes(PROVIDER_CLASS_LINE) || contents.includes('UIWindow(frame:')) {
            throw new Error(
                'withIosSceneLifecycle: AppDelegate.swift does not match the Expo SDK 57 template. Update or remove this plugin.'
            )
        }
        cfg.modResults.contents = contents
        return cfg
    })
}

module.exports = function withIosSceneLifecycle(config) {
    config = withSceneManifest(config)
    config = withFactoryProviderAppDelegate(config)
    return IOSConfig.XcodeProjectFile.withBuildSourceFile(config, {
        filePath: 'SceneDelegate.swift',
        contents: SCENE_DELEGATE,
        overwrite: true,
    })
}
