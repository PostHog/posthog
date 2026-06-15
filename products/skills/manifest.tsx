import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
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
        skill: (name: string, params?: { file?: string; version?: number }): string =>
            combineUrl(`/skills/${name}`, params).url,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Skills',
            intents: [ProductKey.LLM_PROMPTS],
            category: ProductItemCategory.TOOLS,
            type: 'llm_skills',
            iconType: 'llm_prompts' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-prompts-light)'] as FileSystemIconColor,
            href: urls.skills(),
            flag: FEATURE_FLAGS.LLM_ANALYTICS_SKILLS,
            sceneKey: 'Skills',
        },
    ],
}
