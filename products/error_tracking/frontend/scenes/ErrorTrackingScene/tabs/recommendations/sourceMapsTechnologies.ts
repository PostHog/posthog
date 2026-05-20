import androidImage from 'scenes/onboarding/sdks/logos/android.svg'
import nextjsImage from 'scenes/onboarding/sdks/logos/nextjs.svg'
import nuxtImage from 'scenes/onboarding/sdks/logos/nuxt.svg'
import reactImage from 'scenes/onboarding/sdks/logos/react.svg'
import viteImage from 'scenes/onboarding/sdks/logos/vite.svg'

export type TechnologyKey =
    | 'auto'
    | 'nextjs'
    | 'nuxt'
    | 'vite'
    | 'rollup'
    | 'webpack'
    | 'react-native'
    | 'ios'
    | 'android'

export interface Technology {
    key: TechnologyKey
    name: string
    image: string | null
    docsLink: string
    envVars: { apiKey: string; projectId: string }
    buildPrompt: (env: { host: string; projectId: number | string }) => string
}

const PLUGIN_ENV = { apiKey: 'POSTHOG_API_KEY', projectId: 'POSTHOG_PROJECT_ID' }
const CLI_ENV = { apiKey: 'POSTHOG_CLI_API_KEY', projectId: 'POSTHOG_CLI_PROJECT_ID' }

const trim = (s: string): string => s.replace(/^\n/, '').replace(/\n+$/, '\n')

const autoPrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for this project so error tracking shows our original source code instead of minified bundles.

Use this project's package manager — detect it from the lockfile (\`pnpm-lock.yaml\` → pnpm, \`yarn.lock\` → yarn, \`bun.lockb\` → bun, \`package-lock.json\` → npm) before installing anything or invoking CLIs. Examples in this prompt use \`npm\` only as a placeholder; translate them (\`pnpm add\`, \`yarn add\`, \`bun add\`, \`pnpm dlx\` / \`npx\`, etc.) to match the project.

Detect the bundler/framework from package.json and apply the matching integration from PostHog's docs:

- Next.js → install \`@posthog/nextjs-config\`, wrap \`next.config\` with \`withPostHogConfig\`.
- Nuxt → install \`@posthog/cli\`, add a \`close\` hook in \`nuxt.config\` that runs \`posthog-cli sourcemap inject\` + \`posthog-cli sourcemap upload\` against \`.output\`.
- Vite / Rollup → install \`@posthog/rollup-plugin\` and add it to the plugins array.
- Webpack → install \`@posthog/webpack-plugin\` and add it to the plugins array.
- React Native (Expo 50+) → install \`@posthog/cli\`, wire \`posthog-react-native/metro\`, add the Expo plugin in \`app.json\`, and apply the gradle / Xcode build phase tweaks.
- iOS native → add a Run Script build phase running \`upload-symbols.sh\`; set Debug Information Format = "DWARF with dSYM File" and \`ENABLE_USER_SCRIPT_SANDBOXING = NO\`.
- Android native → apply the \`com.posthog.android\` gradle plugin (AGP 8+).
- Anything else → install \`@posthog/cli\` and run \`posthog-cli sourcemap inject\` + \`posthog-cli sourcemap upload\` against the build output directory as a CI step.

Env vars available to the build terminal (\`.env\`, CI secrets, shell exports — whatever this project already uses) — use the set that matches the chosen integration:

- Plugin integrations (Next.js, Vite, Rollup, Webpack): \`POSTHOG_API_KEY\`, \`POSTHOG_PROJECT_ID\`.
- CLI integrations (Nuxt, React Native, iOS, Android, generic): \`POSTHOG_CLI_API_KEY\`, \`POSTHOG_CLI_PROJECT_ID\`.

The PostHog host is fixed for this project — hardcode \`${host}\` everywhere it's referenced (plugin config \`host\` option, CLI \`--host\` flag). Do not introduce a host env var. The project ID value to set in the env var above is \`${projectId}\`.

After applying changes, trigger a build using whatever command this project actually uses (inspect \`package.json\` scripts, \`Fastfile\`, \`build.gradle\`, CI config, etc. before guessing — don't default to \`npm run build\` / \`./gradlew assembleRelease\` if the project has a custom command).

Read the build output carefully: look for PostHog plugin/CLI log lines indicating the upload happened (e.g. "uploading source maps", "uploaded symbol set", "uploaded N files"). If those lines are absent, or you see PostHog-related errors / warnings / non-zero exits, stop and surface them to me before moving on — the integration likely isn't wired up correctly.

Then ask me whether to wire up a quick verification — a "Throw test error" button (or an equivalent invocation if the project has no UI) that calls \`posthog.captureException(new Error('PostHog source maps test'))\` — so I can trigger one error against the new build and confirm the stack trace symbolicates back to original source in PostHog.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps
`)

const nextjsPrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for my Next.js app.

Use this project's package manager — detect it from the lockfile (\`pnpm-lock.yaml\` → pnpm, \`yarn.lock\` → yarn, \`bun.lockb\` → bun, \`package-lock.json\` → npm) before installing anything. The \`npm\` commands below are placeholders; translate them (\`pnpm add\`, \`yarn add\`, \`bun add\`, etc.) accordingly.

1. Install the integration:

    npm install @posthog/nextjs-config

2. Wrap \`next.config.js\` (or \`.mjs\`) with \`withPostHogConfig\`:

    import { withPostHogConfig } from "@posthog/nextjs-config";

    const nextConfig = { /* ... */ };

    export default withPostHogConfig(nextConfig, {
      personalApiKey: process.env.POSTHOG_API_KEY,
      projectId: process.env.POSTHOG_PROJECT_ID,
      host: "${host}",
      sourcemaps: {
        enabled: true,
        releaseName: "my-application",
        releaseVersion: "1.0.0",
        deleteAfterUpload: true,
      },
    });

3. Env vars available to the build terminal (\`.env\`, CI secrets, shell exports — whatever this project already uses; host is hardcoded above, don't introduce a host env var):
   - \`POSTHOG_API_KEY\` — personal API key with \`error_tracking:write\`
   - \`POSTHOG_PROJECT_ID\` = ${projectId}

4. Trigger a build using whatever command this project actually uses — check \`package.json\` scripts (\`build\`, \`build:prod\`, etc.), CI config, or any \`README\`/Makefile before defaulting to \`npm run build\`. Then confirm \`.js.map\` files are produced under \`.next\`.

5. Read the build output: \`@posthog/nextjs-config\` should log lines about uploading source maps to PostHog. If you don't see them, or you see PostHog-related errors / warnings / non-zero exits, stop and surface them to me before continuing.

6. After that, ask me whether to add a "Throw test error" button to the app that calls \`posthog.captureException(new Error('PostHog source maps test'))\` — I want to fire one real error against the new build to confirm the stack trace symbolicates back to my original TSX/TS source.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps/nextjs
`)

const nuxtPrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for my Nuxt app.

Use this project's package manager — detect it from the lockfile (\`pnpm-lock.yaml\` → pnpm, \`yarn.lock\` → yarn, \`bun.lockb\` → bun, \`package-lock.json\` → npm) before installing anything or invoking CLIs. The \`npm\` commands below are placeholders; translate them (\`pnpm add\` / \`pnpm dlx\`, \`yarn add\`, \`bun add\` / \`bunx\`, \`npx\`, etc.) accordingly. Prefer adding \`@posthog/cli\` as a devDependency over a global install — the build hooks just need it on PATH or via \`npx\`.

1. Install the CLI:

    npm install -g @posthog/cli

2. Add a \`close\` hook to \`nuxt.config.js\` so it injects + uploads after every build:

    import { execSync } from 'child_process'

    export default defineNuxtConfig({
      sourcemap: { client: true },
      hooks: {
        close: async () => {
          execSync("posthog-cli sourcemap inject --directory '.output' --host '${host}'", { stdio: 'inherit' })
          execSync("posthog-cli sourcemap upload --directory '.output' --host '${host}'", { stdio: 'inherit' })
        },
      },
    })

3. Env vars available to the build terminal (\`.env\`, CI secrets, shell exports — whatever this project already uses; host is passed as a CLI flag above, don't introduce a host env var):
   - \`POSTHOG_CLI_API_KEY\` — personal API key with \`error_tracking:write\` and \`organization:read\`
   - \`POSTHOG_CLI_PROJECT_ID\` = ${projectId}

4. Trigger a build using whatever command this project actually uses — check \`package.json\` scripts and CI config before defaulting to \`nuxt build\`. Confirm the build runs the \`close\` hook and that \`.mjs.map\` files are produced under \`.output\`.

5. Read the build output: the \`posthog-cli sourcemap inject\` / \`upload\` commands should log lines about injecting + uploading source maps. If you don't see them, or you see PostHog-related errors / warnings / non-zero exits from the CLI, stop and surface them to me before continuing.

6. After that, ask me whether to add a "Throw test error" button to a page in the app that calls \`posthog.captureException(new Error('PostHog source maps test'))\` — I want to trigger one error against the new build and confirm the stack trace symbolicates back to my Vue/TS source in PostHog.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps/nuxt
`)

const vitePrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for my Vite app.

Use this project's package manager — detect it from the lockfile (\`pnpm-lock.yaml\` → pnpm, \`yarn.lock\` → yarn, \`bun.lockb\` → bun, \`package-lock.json\` → npm) before installing anything. The \`npm\` commands below are placeholders; translate them (\`pnpm add\`, \`yarn add\`, \`bun add\`, etc.) accordingly.

1. Install the plugin (Vite reuses the rollup plugin):

    npm install @posthog/rollup-plugin

2. Add it to \`vite.config.js\` / \`vite.config.ts\`:

    import { defineConfig } from 'vite'
    import posthog from '@posthog/rollup-plugin'

    export default defineConfig({
      plugins: [
        posthog({
          personalApiKey: process.env.POSTHOG_API_KEY,
          projectId: process.env.POSTHOG_PROJECT_ID,
          host: '${host}',
          sourcemaps: {
            enabled: true,
            releaseName: 'my-application',
            releaseVersion: '1.0.0',
            deleteAfterUpload: true,
          },
        }),
      ],
    })

3. Env vars available to the build terminal (\`.env\`, CI secrets, shell exports — whatever this project already uses; host is hardcoded above, don't introduce a host env var):
   - \`POSTHOG_API_KEY\` — personal API key with \`error_tracking:write\`
   - \`POSTHOG_PROJECT_ID\` = ${projectId}

4. Trigger a build using whatever command this project actually uses — check \`package.json\` scripts and CI config before defaulting to \`npm run build\`.

5. Read the build output: \`@posthog/rollup-plugin\` should log lines about uploading source maps to PostHog. If you don't see them, or you see PostHog-related errors / warnings / non-zero exits, stop and surface them to me before continuing.

6. After that, ask me whether to add a "Throw test error" button to the app that calls \`posthog.captureException(new Error('PostHog source maps test'))\` — I want to fire one error against the new build to confirm the stack trace symbolicates back to my original source.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps/vite
`)

const rollupPrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for my Rollup project.

Use this project's package manager — detect it from the lockfile (\`pnpm-lock.yaml\` → pnpm, \`yarn.lock\` → yarn, \`bun.lockb\` → bun, \`package-lock.json\` → npm) before installing anything. The \`npm\` commands below are placeholders; translate them (\`pnpm add\`, \`yarn add\`, \`bun add\`, etc.) accordingly.

1. Install the plugin:

    npm install @posthog/rollup-plugin

2. Add it to \`rollup.config.js\`:

    import posthog from '@posthog/rollup-plugin'

    export default {
      input: 'src/index.js',
      output: { dir: 'dist', format: 'es' },
      plugins: [
        posthog({
          personalApiKey: process.env.POSTHOG_API_KEY,
          projectId: process.env.POSTHOG_PROJECT_ID,
          host: '${host}',
          sourcemaps: {
            enabled: true,
            releaseName: 'my-application',
            releaseVersion: '1.0.0',
            deleteAfterUpload: true,
          },
        }),
      ],
    }

3. Env vars available to the build terminal (\`.env\`, CI secrets, shell exports — whatever this project already uses; host is hardcoded above, don't introduce a host env var):
   - \`POSTHOG_API_KEY\` — personal API key with \`error_tracking:write\`
   - \`POSTHOG_PROJECT_ID\` = ${projectId}

4. Trigger a build using whatever command this project actually uses — check \`package.json\` scripts and CI config to find the real build command (e.g. \`rollup -c\`, a custom \`build\` script).

5. Read the build output: \`@posthog/rollup-plugin\` should log lines about uploading source maps to PostHog. If you don't see them, or you see PostHog-related errors / warnings / non-zero exits, stop and surface them to me before continuing.

6. After that, ask me whether to add a quick verification — a "Throw test error" button if the bundle ships a UI, or a one-off invocation in the entry file otherwise — that calls \`posthog.captureException(new Error('PostHog source maps test'))\` so I can confirm the stack trace symbolicates back to my original source in PostHog.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps/rollup
`)

const webpackPrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for my Webpack project.

Use this project's package manager — detect it from the lockfile (\`pnpm-lock.yaml\` → pnpm, \`yarn.lock\` → yarn, \`bun.lockb\` → bun, \`package-lock.json\` → npm) before installing anything. The \`npm\` commands below are placeholders; translate them (\`pnpm add\`, \`yarn add\`, \`bun add\`, etc.) accordingly.

1. Install the plugin:

    npm install @posthog/webpack-plugin

2. Add it to \`webpack.config.js\`:

    const PostHogPlugin = require('@posthog/webpack-plugin')

    module.exports = {
      // ... existing config
      plugins: [
        new PostHogPlugin({
          personalApiKey: process.env.POSTHOG_API_KEY,
          projectId: process.env.POSTHOG_PROJECT_ID,
          host: '${host}',
          sourcemaps: {
            enabled: true,
            releaseName: 'my-application',
            releaseVersion: '1.0.0',
            deleteAfterUpload: true,
          },
        }),
      ],
    }

3. Env vars available to the build terminal (\`.env\`, CI secrets, shell exports — whatever this project already uses; host is hardcoded above, don't introduce a host env var):
   - \`POSTHOG_API_KEY\` — personal API key with \`error_tracking:write\`
   - \`POSTHOG_PROJECT_ID\` = ${projectId}

4. Trigger a build using whatever command this project actually uses — check \`package.json\` scripts and CI config to find the real build command (e.g. \`webpack --mode production\`, a custom \`build\` script).

5. Read the build output: \`@posthog/webpack-plugin\` should log lines about uploading source maps to PostHog. If you don't see them, or you see PostHog-related errors / warnings / non-zero exits, stop and surface them to me before continuing.

6. After that, ask me whether to add a "Throw test error" button to the app that calls \`posthog.captureException(new Error('PostHog source maps test'))\` — I want to trigger one error against the new build and confirm the stack trace symbolicates back to my original source in PostHog.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps/webpack
`)

const reactNativePrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for my React Native (Expo 50+) app.

Use this project's package manager — detect it from the lockfile (\`pnpm-lock.yaml\` → pnpm, \`yarn.lock\` → yarn, \`bun.lockb\` → bun, \`package-lock.json\` → npm) before installing anything or invoking CLIs. The \`npm\` commands below are placeholders; translate them accordingly. Prefer adding \`@posthog/cli\` as a devDependency over a global install — the Metro / Xcode / gradle integrations just need it resolvable.

1. Install the CLI:

    npm install -g @posthog/cli

2. Use the PostHog Metro config — \`metro.config.js\`:

    const { getPostHogExpoConfig } = require('posthog-react-native/metro')
    const config = getPostHogExpoConfig(__dirname)
    module.exports = config

3. Register the Expo plugin in \`app.json\`:

    {
      "expo": {
        "plugins": ["posthog-react-native/expo"]
      }
    }

4. Android — in \`android/app/build.gradle\`, above the \`android\` block:

    apply from: new File(["node", "--print", "require('path').join(require('path').dirname(require.resolve('posthog-react-native')), '..', 'tooling', 'posthog.gradle')"].execute().text.trim())

5. iOS — in the "Bundle React Native code" build phase, call \`posthog-xcode.sh\` then \`react-native-xcode.sh\`. Disable User Script Sandboxing (\`ENABLE_USER_SCRIPT_SANDBOXING=NO\`).

6. Env vars available to the build terminal (\`.env\`, CI secrets, shell exports — whatever this project already uses; use \`--host '${host}'\` directly in the upload commands the Metro / gradle / Xcode integrations invoke — don't introduce a host env var):
   - \`POSTHOG_CLI_API_KEY\` — personal API key with \`error_tracking:write\` and \`organization:read\`
   - \`POSTHOG_CLI_PROJECT_ID\` = ${projectId}

7. Trigger a release build for both iOS and Android using whatever commands this project uses (e.g. \`eas build\`, \`expo run\`, native \`xcodebuild\` / \`./gradlew assembleRelease\`, or a custom script — check \`package.json\`, \`eas.json\`, and CI config).

8. Read the build output for both platforms: the PostHog Metro plugin (on the JS bundle), the gradle plugin (Android), and the iOS Run Script / \`posthog-cli\` invocations should all log lines about uploading source maps + dSYMs. If any of those are missing, or you see PostHog-related errors / warnings / non-zero exits, stop and surface them to me before continuing.

9. After that, ask me whether to add a "Throw test error" button to a screen in the app that calls \`posthog.captureException(new Error('PostHog source maps test'))\` — I want to fire one error against the new release build and confirm the stack trace symbolicates back to my original TSX/TS source in PostHog.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps/react-native
`)

const iosPrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog dSYM uploads for my iOS app.

If this project also has a JS side (React Native, Capacitor, etc.) and a lockfile, use that project's package manager (\`pnpm-lock.yaml\` → pnpm, \`yarn.lock\` → yarn, \`bun.lockb\` → bun, \`package-lock.json\` → npm) instead of defaulting to \`npm install -g\`. For pure-native iOS projects without Node tooling, Homebrew (\`brew install posthog/posthog/cli\`) or downloading the release binary is usually preferable to a global npm install.

1. Install the CLI (only required if you build outside Xcode):

    npm install -g @posthog/cli

2. Xcode build settings (Release config):
   - Debug Information Format = "DWARF with dSYM File"
   - ENABLE_USER_SCRIPT_SANDBOXING = NO

3. Add a Run Script build phase that uploads symbols on every build.

   Swift Package Manager:
       \${BUILD_DIR%/Build/*}/SourcePackages/checkouts/posthog-ios/build-tools/upload-symbols.sh

   CocoaPods:
       \${PODS_ROOT}/PostHog/build-tools/upload-symbols.sh

   For source-context support, prefix with \`POSTHOG_INCLUDE_SOURCE=1\`.

4. Add this to the Run Script's Input Files section:

    $(DWARF_DSYM_FOLDER_PATH)/$(DWARF_DSYM_FILE_NAME)/Contents/Resources/DWARF/$(EXECUTABLE_NAME)

5. Env vars available to the build terminal (\`.env\`, CI secrets, shell exports — whatever this project already uses; pass \`--host '${host}'\` to \`upload-symbols.sh\` rather than introducing a host env var):
   - \`POSTHOG_CLI_API_KEY\` — personal API key with \`error_tracking:write\`
   - \`POSTHOG_CLI_PROJECT_ID\` = ${projectId}

6. Trigger an archive / release build using whatever command this project uses (Xcode Archive, \`xcodebuild archive\`, fastlane, or a CI script — check \`Fastfile\`, CI config, and any \`README\` first).

7. Read the build output: the \`upload-symbols.sh\` Run Script (and \`posthog-cli\` underneath it) should log lines about uploading dSYMs. If you don't see them, or you see PostHog-related errors / warnings / non-zero exits from the Run Script phase, stop and surface them to me before continuing.

8. After that, ask me whether to add a "Throw test error" button to a screen in the app that calls the iOS SDK's exception capture API (the Swift equivalent of \`posthog.captureException(...)\`) — I want to fire one error against the archived build and confirm the stack trace symbolicates back to my Swift source in PostHog.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps/ios
`)

const androidPrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog ProGuard/R8 mapping uploads for my Android app.

1. Requirements: Android Gradle Plugin 8+ and PostHog CLI v0.7.4+.

2. Apply the PostHog gradle plugin in \`app/build.gradle.kts\` (or the Groovy equivalent):

    plugins {
        id("com.android.application")
        id("com.posthog.android") version "<latest>"
    }

3. Env vars available to the build terminal (\`.env\`, CI secrets, shell exports — whatever this project already uses; hardcode the host as \`postHogHost = "${host}"\` on \`PostHogCliExecTask\` — don't introduce a host env var):
   - \`POSTHOG_CLI_API_KEY\` — personal API key with \`error_tracking:write\` and \`organization:read\`
   - \`POSTHOG_CLI_PROJECT_ID\` = ${projectId}

   (The plugin also exposes \`postHogApiKey\` / \`postHogProjectId\` on \`PostHogCliExecTask\` for inline configuration.)

4. Trigger a release build using whatever command this project uses (e.g. \`./gradlew assembleRelease\`, \`./gradlew bundleRelease\`, or a fastlane lane — check the project's \`Fastfile\`, CI config, and any \`README\` first). The plugin uploads the mapping automatically as part of the release build.

5. Read the gradle output: the \`com.posthog.android\` plugin's \`PostHogCliExecTask\` should log lines about uploading the ProGuard/R8 mapping to PostHog. If you don't see them, or you see PostHog-related errors / warnings / non-zero exits from that task, stop and surface them to me before continuing.

6. After that, ask me whether to add a "Throw test error" button to a screen in the app that calls the Android SDK's exception capture API (the Kotlin/Java equivalent of \`posthog.captureException(...)\`) — I want to fire one error against the release build and confirm the stack trace deobfuscates back to my Kotlin/Java source in PostHog.

Docs: https://posthog.com/docs/error-tracking/upload-mappings/android
`)

export const SOURCE_MAPS_TECHNOLOGIES: Technology[] = [
    {
        key: 'auto',
        name: 'Auto detect',
        image: null,
        docsLink: 'https://posthog.com/docs/error-tracking/upload-source-maps',
        envVars: PLUGIN_ENV,
        buildPrompt: autoPrompt,
    },
    {
        key: 'nextjs',
        name: 'Next.js',
        image: nextjsImage,
        docsLink: 'https://posthog.com/docs/error-tracking/upload-source-maps/nextjs',
        envVars: PLUGIN_ENV,
        buildPrompt: nextjsPrompt,
    },
    {
        key: 'nuxt',
        name: 'Nuxt',
        image: nuxtImage,
        docsLink: 'https://posthog.com/docs/error-tracking/upload-source-maps/nuxt',
        envVars: CLI_ENV,
        buildPrompt: nuxtPrompt,
    },
    {
        key: 'vite',
        name: 'Vite',
        image: viteImage,
        docsLink: 'https://posthog.com/docs/error-tracking/upload-source-maps/vite',
        envVars: PLUGIN_ENV,
        buildPrompt: vitePrompt,
    },
    {
        key: 'rollup',
        name: 'Rollup',
        image: null,
        docsLink: 'https://posthog.com/docs/error-tracking/upload-source-maps/rollup',
        envVars: PLUGIN_ENV,
        buildPrompt: rollupPrompt,
    },
    {
        key: 'webpack',
        name: 'Webpack',
        image: null,
        docsLink: 'https://posthog.com/docs/error-tracking/upload-source-maps/webpack',
        envVars: PLUGIN_ENV,
        buildPrompt: webpackPrompt,
    },
    {
        key: 'react-native',
        name: 'React Native',
        image: reactImage,
        docsLink: 'https://posthog.com/docs/error-tracking/upload-source-maps/react-native',
        envVars: CLI_ENV,
        buildPrompt: reactNativePrompt,
    },
    {
        key: 'ios',
        name: 'iOS',
        image: null,
        docsLink: 'https://posthog.com/docs/error-tracking/upload-source-maps/ios',
        envVars: CLI_ENV,
        buildPrompt: iosPrompt,
    },
    {
        key: 'android',
        name: 'Android',
        image: androidImage,
        docsLink: 'https://posthog.com/docs/error-tracking/upload-mappings/android',
        envVars: CLI_ENV,
        buildPrompt: androidPrompt,
    },
]

export function getTechnology(key: TechnologyKey): Technology {
    return SOURCE_MAPS_TECHNOLOGIES.find((t) => t.key === key) ?? SOURCE_MAPS_TECHNOLOGIES[0]
}
