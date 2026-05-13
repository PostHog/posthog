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
    envVars: { apiKey: string; host: string; projectId: string }
    buildPrompt: (env: { host: string; projectId: number | string }) => string
}

const PLUGIN_ENV = { apiKey: 'POSTHOG_API_KEY', host: 'POSTHOG_HOST', projectId: 'POSTHOG_PROJECT_ID' }
const CLI_ENV = { apiKey: 'POSTHOG_CLI_API_KEY', host: 'POSTHOG_CLI_HOST', projectId: 'POSTHOG_CLI_PROJECT_ID' }
const NEXTJS_ENV = { apiKey: 'POSTHOG_API_KEY', host: 'NEXT_PUBLIC_POSTHOG_HOST', projectId: 'POSTHOG_PROJECT_ID' }

const trim = (s: string): string => s.replace(/^\n/, '').replace(/\n+$/, '\n')

const autoPrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for this project so error tracking shows our original source code instead of minified bundles.

Detect the bundler/framework from package.json and apply the matching integration from PostHog's docs:

- Next.js → install \`@posthog/nextjs-config\`, wrap \`next.config\` with \`withPostHogConfig\`.
- Nuxt → install \`@posthog/cli\`, add a \`close\` hook in \`nuxt.config\` that runs \`posthog-cli sourcemap inject\` + \`posthog-cli sourcemap upload\` against \`.output\`.
- Vite / Rollup → install \`@posthog/rollup-plugin\` and add it to the plugins array.
- Webpack → install \`@posthog/webpack-plugin\` and add it to the plugins array.
- React Native (Expo 50+) → install \`@posthog/cli\`, wire \`posthog-react-native/metro\`, add the Expo plugin in \`app.json\`, and apply the gradle / Xcode build phase tweaks.
- iOS native → add a Run Script build phase running \`upload-symbols.sh\`; set Debug Information Format = "DWARF with dSYM File" and \`ENABLE_USER_SCRIPT_SANDBOXING = NO\`.
- Android native → apply the \`com.posthog.android\` gradle plugin (AGP 8+).
- Anything else → install \`@posthog/cli\` and run \`posthog-cli sourcemap inject\` + \`posthog-cli sourcemap upload\` against the build output directory as a CI step.

Env vars already provisioned in CI — use the set that matches the chosen integration:

- Plugin integrations (Next.js, Vite, Rollup, Webpack): \`POSTHOG_API_KEY\`, \`POSTHOG_PROJECT_ID\`, \`POSTHOG_HOST\` (Next.js uses \`NEXT_PUBLIC_POSTHOG_HOST\` instead).
- CLI integrations (Nuxt, React Native, iOS, Android, generic): \`POSTHOG_CLI_API_KEY\`, \`POSTHOG_CLI_PROJECT_ID\`, \`POSTHOG_CLI_HOST\`.

Values: host \`${host}\`, project ID \`${projectId}\`.

After applying changes, run a release build and confirm a new symbol set appears in PostHog → Error tracking → Symbol sets.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps
`)

const nextjsPrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for my Next.js app.

1. Install the integration:

    npm install @posthog/nextjs-config

2. Wrap \`next.config.js\` (or \`.mjs\`) with \`withPostHogConfig\`:

    import { withPostHogConfig } from "@posthog/nextjs-config";

    const nextConfig = { /* ... */ };

    export default withPostHogConfig(nextConfig, {
      personalApiKey: process.env.POSTHOG_API_KEY,
      projectId: process.env.POSTHOG_PROJECT_ID,
      host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
      sourcemaps: {
        enabled: true,
        releaseName: "my-application",
        releaseVersion: "1.0.0",
        deleteAfterUpload: true,
      },
    });

3. Env vars already provisioned in CI:
   - \`POSTHOG_API_KEY\` — personal API key with \`error_tracking:write\`
   - \`POSTHOG_PROJECT_ID\` = ${projectId}
   - \`NEXT_PUBLIC_POSTHOG_HOST\` = ${host}

4. Run \`npm run build\` and confirm \`.js.map\` files are produced under \`.next\` and a new symbol set appears in PostHog.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps/nextjs
`)

const nuxtPrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for my Nuxt app.

1. Install the CLI:

    npm install -g @posthog/cli

2. Add a \`close\` hook to \`nuxt.config.js\` so it injects + uploads after every build:

    import { execSync } from 'child_process'

    export default defineNuxtConfig({
      sourcemap: { client: true },
      hooks: {
        close: async () => {
          execSync("posthog-cli sourcemap inject --directory '.output'", { stdio: 'inherit' })
          execSync("posthog-cli sourcemap upload --directory '.output'", { stdio: 'inherit' })
        },
      },
    })

3. Env vars already provisioned in CI:
   - \`POSTHOG_CLI_API_KEY\` — personal API key with \`error_tracking:write\` and \`organization:read\`
   - \`POSTHOG_CLI_PROJECT_ID\` = ${projectId}
   - \`POSTHOG_CLI_HOST\` = ${host}

4. Run \`nuxt build\` and confirm the injected \`.mjs.map\` files reach PostHog (look for the new symbol set).

Docs: https://posthog.com/docs/error-tracking/upload-source-maps/nuxt
`)

const vitePrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for my Vite app.

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
          host: process.env.POSTHOG_HOST,
          sourcemaps: {
            enabled: true,
            releaseName: 'my-application',
            releaseVersion: '1.0.0',
            deleteAfterUpload: true,
          },
        }),
      ],
    })

3. Env vars already provisioned in CI:
   - \`POSTHOG_API_KEY\` — personal API key with \`error_tracking:write\`
   - \`POSTHOG_PROJECT_ID\` = ${projectId}
   - \`POSTHOG_HOST\` = ${host}

4. Run \`npm run build\` and confirm a new symbol set appears in PostHog.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps/vite
`)

const rollupPrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for my Rollup project.

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
          host: process.env.POSTHOG_HOST,
          sourcemaps: {
            enabled: true,
            releaseName: 'my-application',
            releaseVersion: '1.0.0',
            deleteAfterUpload: true,
          },
        }),
      ],
    }

3. Env vars already provisioned in CI:
   - \`POSTHOG_API_KEY\` — personal API key with \`error_tracking:write\`
   - \`POSTHOG_PROJECT_ID\` = ${projectId}
   - \`POSTHOG_HOST\` = ${host}

4. Run the build and confirm a new symbol set appears in PostHog.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps/rollup
`)

const webpackPrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for my Webpack project.

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
          host: process.env.POSTHOG_HOST,
          sourcemaps: {
            enabled: true,
            releaseName: 'my-application',
            releaseVersion: '1.0.0',
            deleteAfterUpload: true,
          },
        }),
      ],
    }

3. Env vars already provisioned in CI:
   - \`POSTHOG_API_KEY\` — personal API key with \`error_tracking:write\`
   - \`POSTHOG_PROJECT_ID\` = ${projectId}
   - \`POSTHOG_HOST\` = ${host}

4. Run the build and confirm a new symbol set appears in PostHog.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps/webpack
`)

const reactNativePrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog source map uploads for my React Native (Expo 50+) app.

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

6. Env vars already provisioned in CI:
   - \`POSTHOG_CLI_API_KEY\` — personal API key with \`error_tracking:write\` and \`organization:read\`
   - \`POSTHOG_CLI_PROJECT_ID\` = ${projectId}
   - \`POSTHOG_CLI_HOST\` = ${host}

7. Run a release build (iOS + Android) and confirm symbol sets appear in PostHog.

Docs: https://posthog.com/docs/error-tracking/upload-source-maps/react-native
`)

const iosPrompt = ({ host, projectId }: { host: string; projectId: number | string }): string =>
    trim(`
Set up PostHog dSYM uploads for my iOS app.

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

5. Env vars already provisioned in CI:
   - \`POSTHOG_CLI_API_KEY\` — personal API key with \`error_tracking:write\`
   - \`POSTHOG_CLI_PROJECT_ID\` = ${projectId}
   - \`POSTHOG_CLI_HOST\` = ${host}

6. Archive a release build and confirm dSYMs land in PostHog.

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

3. Env vars already provisioned in CI:
   - \`POSTHOG_CLI_API_KEY\` — personal API key with \`error_tracking:write\` and \`organization:read\`
   - \`POSTHOG_CLI_PROJECT_ID\` = ${projectId}
   - \`POSTHOG_CLI_HOST\` = ${host}

   (If you'd rather configure inline, the plugin exposes \`postHogApiKey\` / \`postHogProjectId\` / \`postHogHost\` on \`PostHogCliExecTask\`.)

4. Run \`./gradlew assembleRelease\`. The plugin uploads the mapping automatically as part of the release build — confirm the symbol set in PostHog.

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
        envVars: NEXTJS_ENV,
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
