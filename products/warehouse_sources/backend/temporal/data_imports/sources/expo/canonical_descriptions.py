from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "builds": {
        "description": "An EAS Build job for the project, with its platform, outcome, and timing.",
        "docs_url": "https://docs.expo.dev/build/introduction/",
        "columns": {
            "id": "Unique identifier for the build.",
            "status": "Build outcome, such as NEW, IN_QUEUE, IN_PROGRESS, FINISHED, ERRORED, or CANCELED.",
            "platform": "Platform the build targets: ANDROID or IOS.",
            "distribution": "How the build is distributed, such as STORE or INTERNAL.",
            "buildProfile": "Name of the eas.json build profile used.",
            "appIdentifier": "Bundle identifier or package name the build produced.",
            "sdkVersion": "Expo SDK version the build used.",
            "appVersion": "App version string set for the build.",
            "appBuildVersion": "Platform build number, such as versionCode or CFBundleVersion.",
            "gitCommitHash": "Commit the build was created from.",
            "gitCommitMessage": "Message of the commit the build was created from.",
            "message": "Message attached to the build when it was started.",
            "priority": "Queue priority the build ran at.",
            "createdAt": "Date and time the build was created.",
            "updatedAt": "Date and time the build was last updated.",
            "completedAt": "Date and time the build finished.",
            "expirationDate": "Date and time the build artifacts expire.",
            "isForIosSimulator": "Whether the build targets the iOS simulator.",
            "error": "Error code and message when the build failed.",
            "artifacts": "URLs of the build output, including the application archive.",
            "initiatingActor": "User or robot that started the build.",
            "updateChannel": "EAS Update channel the build is bound to.",
            "runtime": "Runtime version the build is compatible with.",
            "metrics": "Timing for the build: queue time, wait time, and build duration.",
        },
    },
    "submissions": {
        "description": "An EAS Submit job that uploaded a build to the App Store or Google Play.",
        "docs_url": "https://docs.expo.dev/submit/introduction/",
        "columns": {
            "id": "Unique identifier for the submission.",
            "status": "Submission outcome, such as IN_QUEUE, IN_PROGRESS, FINISHED, ERRORED, or CANCELED.",
            "platform": "Store the submission targets: ANDROID or IOS.",
            "androidConfig": "Google Play settings used, including the track and rollout.",
            "iosConfig": "App Store Connect settings used, including the app identifier.",
            "error": "Error code and message when the submission failed.",
        },
    },
}
