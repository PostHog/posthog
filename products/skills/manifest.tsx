import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Skills',
    scenes: {
        Skills: {
            import: () => import('./frontend/LLMSkillsScene'),
            projectBased: true,
            name: 'Skills',
            description: 'Manage versioned agent skills that any MCP-connected agent can discover and use.',
            layout: 'app-container',
            iconType: 'llm_prompts',
        },
        Skill: {
            import: () => import('./frontend/LLMSkillScene'),
            projectBased: true,
            name: 'Skill',
            layout: 'app-container',
            iconType: 'llm_prompts',
        },
    },
    routes: {
        '/skills': ['Skills', 'skills'],
        // Category tabs (e.g. /skills/scouts) must precede the `/skills/:name` wildcard so they
        // aren't captured as a skill named after the tab. Route order = match precedence.
        '/skills/scouts': ['Skills', 'skillsScouts'],
        '/skills/:name': ['Skill', 'skill'],
    },
    redirects: {
        '/prompt-management/skills': (_params, searchParams, hashParams) =>
            combineUrl(urls.skills(), searchParams, hashParams).url,
        '/prompt-management/skills/:name': (params, searchParams, hashParams) =>
            combineUrl(urls.skill(params.name), searchParams, hashParams).url,
        '/llm-analytics/skills': (_params, searchParams, hashParams) =>
            combineUrl(urls.skills(), searchParams, hashParams).url,
        '/llm-analytics/skills/:name': (params, searchParams, hashParams) =>
            combineUrl(urls.skill(params.name), searchParams, hashParams).url,
    },
    urls: {
        skills: (): string => '/skills',
        // A category tab under /skills (e.g. /skills/scouts). The tab key is the URL segment.
        skillsCategoryTab: (categoryTab: string): string => `/skills/${categoryTab}`,
        skill: (name: string, params?: { file?: string; version?: number }): string =>
            combineUrl(`/skills/${name}`, params).url,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Skills',
            intents: [ProductKey.SKILLS],
            category: ProductItemCategory.TOOLS,
            type: 'llm_skills',
            iconType: 'llm_prompts' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-prompts-light)'] as FileSystemIconColor,
            href: urls.skills(),
            sceneKey: 'Skills',
        },
    ],
}
