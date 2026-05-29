/**
 * Storybook for the agent platform UI surface.
 *
 * One Storybook, two contributing locations:
 *  - `packages/agent-chat/src/**` for the chat dock stories
 *  - `services/agent-console/src/**` for the console-page stories
 *
 * Story sidebar groups (via `title:` in each .stories.tsx):
 *  - "Agent Chat/*" — chat package
 *  - "Console/Pages/*" — console pages
 *
 * Tailwind v4 is wired via `@tailwindcss/vite`; the import in
 * `.storybook/preview.tsx` of `./storybook.css` pulls in the @theme +
 * @source directives so utilities get generated against both packages'
 * source trees.
 */

import type { StorybookConfig } from '@storybook/react-vite'
import path from 'node:path'

const config: StorybookConfig = {
    stories: [
        '../src/**/*.stories.@(js|jsx|mjs|ts|tsx)',
        '../../../packages/agent-chat/src/**/*.stories.@(js|jsx|mjs|ts|tsx)',
    ],
    addons: ['@storybook/addon-docs', 'storybook-dark-mode'],
    // `mockServiceWorker.js` is served at `/` so MSW can register the
    // worker. Storybook is the only environment that boots MSW — the
    // Next.js app surface stays MSW-free.
    staticDirs: ['./public'],
    framework: {
        name: '@storybook/react-vite',
        options: {},
    },
    viteFinal: async (config) => {
        // `@storybook/react-vite` already registers `@vitejs/plugin-react` —
        // do not add a second instance here or React Refresh double-injects
        // its preamble and Vite chokes on `prevRefreshSig` being redeclared.
        const { default: tailwindcss } = await import('@tailwindcss/vite')

        config.plugins = [...(config.plugins ?? []), tailwindcss()]
        config.resolve = {
            ...config.resolve,
            alias: {
                ...config.resolve?.alias,
                '@': path.resolve(__dirname, '../src'),
                // Storybook runs under Vite, not Next.js. The shell + page
                // clients call `useRouter()` etc. — stub them out so the
                // real components mount cleanly in stories.
                'next/navigation': path.resolve(__dirname, './mocks/next-navigation.tsx'),
            },
        }
        return config
    },
}

export default config
