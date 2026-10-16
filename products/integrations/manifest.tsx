import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Integrations',
    scenes: {
        GitHubConnect: {
            name: 'Connect GitHub',
            import: () => import('./frontend/GitHubConnectScene'),
            projectBased: true,
            layout: 'plain',
        },
    },
    routes: {
        // pinned: the PostHog MCP hands this path to AI chat users, so renaming it breaks those links.
        '/integrations/github/connect': ['GitHubConnect', 'githubConnect'],
    },
    urls: {
        githubConnect: (): string => '/integrations/github/connect',
    },
}
