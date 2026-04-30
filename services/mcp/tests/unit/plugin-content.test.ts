import { describe, expect, it } from 'vitest'

import {
    type BundleEntry,
    type SkillEntry,
    buildBundlePluginFiles,
    buildCorePluginFiles,
    buildMarketplaceJson,
    buildSkillPluginFiles,
} from '@/lib/plugin-content'

const SKILLS: SkillEntry[] = [
    {
        name: 'feature-flags-react',
        description: 'Feature flags for React',
        version: '1.12.1',
        files: { 'SKILL.md': '# Feature flags React', 'references/react.md': '# React docs' },
    },
    {
        name: 'error-tracking-react',
        description: 'Error tracking for React',
        version: '1.12.1',
        files: { 'SKILL.md': '# Error tracking React' },
    },
    {
        name: 'error-tracking-nextjs',
        description: 'Error tracking for Next.js',
        version: '1.12.1',
        files: { 'SKILL.md': '# Error tracking Next.js' },
    },
]

const BUNDLE: BundleEntry = {
    name: 'react',
    displayName: 'PostHog for React',
    description: 'Analytics, feature flags, and error tracking for React',
    keywords: ['react', 'javascript'],
    skills: ['feature-flags-react', 'error-tracking-react'],
}

describe('buildCorePluginFiles', () => {
    it('includes plugin.json with correct name and passed version', () => {
        const files = buildCorePluginFiles('1.12.1')
        const pluginJson = JSON.parse(files['.claude-plugin/plugin.json']!)

        expect(pluginJson.name).toBe('posthog')
        expect(pluginJson.version).toBe('1.12.1')
        expect(pluginJson.author.name).toBe('PostHog')
    })

    it('includes mcp.json pointing to MCP server', () => {
        const files = buildCorePluginFiles('1.0.0')
        const mcpJson = JSON.parse(files['mcp.json']!)

        expect(mcpJson.mcpServers.posthog.type).toBe('http')
        expect(mcpJson.mcpServers.posthog.url).toContain('posthog.com')
    })
})

describe('buildSkillPluginFiles', () => {
    it('includes plugin.json with dependency on core', () => {
        const files = buildSkillPluginFiles(SKILLS[0]!)
        const pluginJson = JSON.parse(files['.claude-plugin/plugin.json']!)

        expect(pluginJson.name).toBe('posthog-feature-flags-react')
        expect(pluginJson.dependencies).toEqual(['posthog'])
        expect(pluginJson.version).toBe('1.12.1')
    })

    it('includes SKILL.md and references at the correct paths', () => {
        const files = buildSkillPluginFiles(SKILLS[0]!)

        expect(files['skills/feature-flags-react/SKILL.md']).toBe('# Feature flags React')
        expect(files['skills/feature-flags-react/references/react.md']).toBe('# React docs')
    })
})

describe('buildBundlePluginFiles', () => {
    it('includes plugin.json with bundle name and dependency on core', () => {
        const files = buildBundlePluginFiles(BUNDLE, SKILLS)
        const pluginJson = JSON.parse(files['.claude-plugin/plugin.json']!)

        expect(pluginJson.name).toBe('posthog-react')
        expect(pluginJson.dependencies).toEqual(['posthog'])
        expect(pluginJson.keywords).toEqual(['react', 'javascript'])
        expect(pluginJson.version).toBe('1.12.1')
    })

    it('inlines all referenced skills', () => {
        const files = buildBundlePluginFiles(BUNDLE, SKILLS)

        expect(files['skills/feature-flags-react/SKILL.md']).toBe('# Feature flags React')
        expect(files['skills/feature-flags-react/references/react.md']).toBe('# React docs')
        expect(files['skills/error-tracking-react/SKILL.md']).toBe('# Error tracking React')
    })

    it('skips skills not found in the skills list', () => {
        const bundle: BundleEntry = {
            ...BUNDLE,
            skills: ['feature-flags-react', 'nonexistent-skill'],
        }
        const files = buildBundlePluginFiles(bundle, SKILLS)

        expect(files['skills/feature-flags-react/SKILL.md']).toBeDefined()
        expect(Object.keys(files).some((k) => k.includes('nonexistent'))).toBe(false)
    })

    it('does not include skills outside the bundle', () => {
        const files = buildBundlePluginFiles(BUNDLE, SKILLS)

        expect(Object.keys(files).some((k) => k.includes('error-tracking-nextjs'))).toBe(false)
    })
})

describe('buildMarketplaceJson', () => {
    const bundles: BundleEntry[] = [
        BUNDLE,
        {
            name: 'nextjs',
            displayName: 'PostHog for Next.js',
            description: 'PostHog for Next.js',
            keywords: ['nextjs'],
            skills: ['error-tracking-nextjs'],
        },
    ]

    it('lists core plugin and bundles (not individual skills)', () => {
        const json = JSON.parse(buildMarketplaceJson(bundles, 'https://mcp.posthog.com'))
        const plugins = json.plugins as Array<{ name: string }>

        expect(plugins).toHaveLength(3) // core + 2 bundles
        expect(plugins[0]!.name).toBe('posthog')
        expect(plugins[1]!.name).toBe('posthog-react')
        expect(plugins[2]!.name).toBe('posthog-nextjs')
    })

    it('points bundles at /git/bundles/:name', () => {
        const json = JSON.parse(buildMarketplaceJson(bundles, 'https://mcp.posthog.com'))
        const plugins = json.plugins as Array<{ source: { url: string } }>

        expect(plugins[1]!.source.url).toBe('https://mcp.posthog.com/git/bundles/react')
        expect(plugins[2]!.source.url).toBe('https://mcp.posthog.com/git/bundles/nextjs')
    })

    it('bundles declare dependency on core', () => {
        const json = JSON.parse(buildMarketplaceJson(bundles, 'https://mcp.posthog.com'))
        const plugins = json.plugins as Array<{ dependencies?: string[] }>

        expect(plugins[1]!.dependencies).toEqual(['posthog'])
    })
})
