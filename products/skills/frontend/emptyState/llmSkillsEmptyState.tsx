import * as puzzlePng from '@posthog/brand/hoggies/png/puzzle'
import { IconLlmPromptManagement } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { LLMSkillPreview } from './LLMSkillPreview'
import { llmSkillsSetupLogic } from './llmSkillsSetupLogic'

const HedgehogPuzzle = pngHoggie(puzzlePng)

export const llmSkillsEmptyState: SceneProductEmptyState = {
    statusLogic: llmSkillsSetupLogic,
    config: {
        productKey: ProductKey.SKILLS,
        productName: 'Skills',
        icon: <IconLlmPromptManagement />,
        accentColor: 'var(--color-product-llm-analytics-light)',
        accentColorDark: 'var(--color-product-llm-analytics-dark)',
        hedgehog: HedgehogPuzzle,
        text: {
            'needs-setup': {
                headline: 'Write a skill once, load it in any agent',
                lead: 'Skills are versioned instructions your coding agents can discover and use. Publish them here and any MCP-connected agent can load them directly, or install them into Claude Code and Codex with automatic updates. Import and export skills as .zip files to share them across teams.',
            },
        },
        primaryAction: {
            label: 'Create your first skill',
            to: urls.skill('new'),
            accessControl: {
                resourceType: AccessControlResourceType.LlmSkill,
                minAccessLevel: AccessControlLevel.Editor,
            },
            dataAttr: 'new-skill-button',
        },
        skippable: false,
        previewLabel: 'Your skills, once published',
        Preview: LLMSkillPreview,
    },
}
