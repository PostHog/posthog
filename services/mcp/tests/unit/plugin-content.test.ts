import { describe, expect, it } from 'vitest'

import {
    buildCorePluginFiles,
    buildMarketplaceJson,
    buildSkillPluginFiles,
    type SkillEntry,
} from '@/lib/plugin-content'

describe('buildCorePluginFiles', () => {
    it('includes plugin.json with correct name and passed version', () => {
        const files = buildCorePluginFiles('1.12.1')
        const raw = files['.claude-plugin/plugin.json']
        expect(raw).toBeDefined()
        const pluginJson = JSON.parse(raw!)

        expect(pluginJson.name).toBe('posthog')
        expect(pluginJson.version).toBe('1.12.1')
        expect(pluginJson.author.name).toBe('PostHog')
    })

    it('includes mcp.json pointing to MCP server', () => {
        const files = buildCorePluginFiles('1.0.0')
        const raw = files['mcp.json']
        expect(raw).toBeDefined()
        const mcpJson = JSON.parse(raw!)

        expect(mcpJson.mcpServers.posthog.type).toBe('http')
        expect(mcpJson.mcpServers.posthog.url).toContain('posthog.com')
    })
})

describe('buildSkillPluginFiles', () => {
    const skill: SkillEntry = {
        name: 'exploring-llm-traces',
        description: 'Debug and inspect LLM traces',
        version: '1.12.1',
        files: {
            'SKILL.md': '---\nname: exploring-llm-traces\n---\n\n# Exploring LLM Traces\n\nContent here.',
            'references/traces.md': '# Trace reference docs',
        },
    }

    it('includes plugin.json with dependency on core', () => {
        const files = buildSkillPluginFiles(skill)
        const raw = files['.claude-plugin/plugin.json']
        expect(raw).toBeDefined()
        const pluginJson = JSON.parse(raw!)

        expect(pluginJson.name).toBe('posthog-exploring-llm-traces')
        expect(pluginJson.dependencies).toEqual(['posthog'])
    })

    it('passes through skill version from frontmatter', () => {
        const files = buildSkillPluginFiles(skill)
        const pluginJson = JSON.parse(files['.claude-plugin/plugin.json']!)

        expect(pluginJson.version).toBe('1.12.1')
    })

    it('includes SKILL.md at the correct path', () => {
        const files = buildSkillPluginFiles(skill)

        expect(files['skills/exploring-llm-traces/SKILL.md']).toBe(skill.files['SKILL.md'])
    })

    it('includes reference files at the correct path', () => {
        const files = buildSkillPluginFiles(skill)

        expect(files['skills/exploring-llm-traces/references/traces.md']).toBe('# Trace reference docs')
    })

    it('includes description from the skill entry', () => {
        const files = buildSkillPluginFiles(skill)
        const raw = files['.claude-plugin/plugin.json']
        expect(raw).toBeDefined()
        const pluginJson = JSON.parse(raw!)

        expect(pluginJson.description).toBe('Debug and inspect LLM traces')
    })
})

describe('buildMarketplaceJson', () => {
    const skills: SkillEntry[] = [
        { name: 'skill-a', description: 'Skill A', version: '1.0.0', files: { 'SKILL.md': '# A' } },
        { name: 'skill-b', description: 'Skill B', version: '1.0.0', files: { 'SKILL.md': '# B' } },
    ]

    it('includes core plugin and all skills', () => {
        const json = JSON.parse(buildMarketplaceJson(skills, 'https://mcp.posthog.com'))
        const plugins = json.plugins as Array<{ name: string }>

        expect(plugins).toHaveLength(3)
        expect(plugins[0]!.name).toBe('posthog')
        expect(plugins[1]!.name).toBe('posthog-skill-a')
        expect(plugins[2]!.name).toBe('posthog-skill-b')
    })

    it('points core plugin at /git/core', () => {
        const json = JSON.parse(buildMarketplaceJson(skills, 'https://mcp.posthog.com'))
        const plugins = json.plugins as Array<{ source: { url: string } }>

        expect(plugins[0]!.source.url).toBe('https://mcp.posthog.com/git/core')
    })

    it('points skill plugins at /git/skills/:name', () => {
        const json = JSON.parse(buildMarketplaceJson(skills, 'https://mcp.posthog.com'))
        const plugins = json.plugins as Array<{ source: { url: string } }>

        expect(plugins[1]!.source.url).toBe('https://mcp.posthog.com/git/skills/skill-a')
        expect(plugins[2]!.source.url).toBe('https://mcp.posthog.com/git/skills/skill-b')
    })

    it('sets marketplace owner', () => {
        const json = JSON.parse(buildMarketplaceJson(skills, 'https://mcp.posthog.com'))

        expect(json.owner.name).toBe('PostHog')
        expect(json.name).toBe('posthog')
    })

    it('skill plugins declare dependency on core', () => {
        const json = JSON.parse(buildMarketplaceJson(skills, 'https://mcp.posthog.com'))
        const plugins = json.plugins as Array<{ dependencies?: string[] }>

        expect(plugins[1]!.dependencies).toEqual(['posthog'])
        expect(plugins[2]!.dependencies).toEqual(['posthog'])
    })
})
