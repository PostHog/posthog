import { defineConfig } from '@rsbuild/core'
import { pluginMdx } from '@rsbuild/plugin-mdx'
import { pluginNodePolyfill } from '@rsbuild/plugin-node-polyfill'
import { pluginReact } from '@rsbuild/plugin-react'
import { pluginSass } from '@rsbuild/plugin-sass'

export default defineConfig({
    plugins: [pluginSass(), pluginReact(), pluginNodePolyfill(), pluginMdx()],
    source: {
        tsconfigPath: './tsconfig.json',
        assetsInclude: [/\.lottie$/],
        alias: {
            '~': './frontend/src',
            lib: './frontend/src/lib',
            scenes: './frontend/src/scenes',
            '@posthog/apps-common': './frontend/@posthog/apps-common/src',
            '@posthog/lemon-ui': './frontend/@posthog/lemon-ui/src',
            '@posthog/ee/exports': ['./ee/frontend/exports', './frontend/@posthog/ee/exports'],
            types: './frontend/types',
            public: './frontend/public',
        },
    },
})
