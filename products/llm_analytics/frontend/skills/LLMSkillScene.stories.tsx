import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import type {
    LLMSkillApi,
    LLMSkillListApi,
    LLMSkillResolveResponseApi,
    LLMSkillVersionSummaryApi,
    UserBasicApi,
} from '../generated/api.schemas'

const MOCK_AUTHOR: UserBasicApi = {
    id: 178,
    uuid: '01853eba-3d18-0000-9d9b-000000000001',
    distinct_id: 'mock-user-178-distinct-id',
    first_name: 'John',
    email: 'john.doe@posthog.com',
    hedgehog_config: null,
}

const SKILL_NAME = 'pdf-extractor'

const SKILL_BODY = `# PDF extractor

## When to use
Use this skill when you need to pull text out of a PDF, fill a form, or merge several PDFs.

## Steps
1. Detect the PDF type (text-based vs scanned).
2. Extract text using the matching strategy.
3. Optionally summarize the result.

## Notes
- Scanned PDFs require OCR.
- Encrypted PDFs need the password supplied as input.
`

function makeVersion(version: number, isLatest: boolean): LLMSkillVersionSummaryApi {
    return {
        id: `skill-version-${version}`,
        version,
        is_latest: isLatest,
        created_at: `2025-01-${String(10 + version).padStart(2, '0')}T10:00:00Z`,
        created_by: MOCK_AUTHOR,
    }
}

const VERSIONS: LLMSkillVersionSummaryApi[] = [
    makeVersion(4, true),
    makeVersion(3, false),
    makeVersion(2, false),
    makeVersion(1, false),
]

const SKILL: LLMSkillApi = {
    id: 'skill-version-4',
    name: SKILL_NAME,
    description: 'Extract text from PDFs, fill forms, and merge files. Use when handling PDFs.',
    body: SKILL_BODY,
    license: 'Apache-2.0',
    compatibility: 'Requires poppler-utils on the host',
    allowed_tools: ['read', 'shell'],
    metadata: {},
    files: [
        { path: 'scripts/extract.sh', content_type: 'text/x-shellscript' },
        { path: 'references/pdf-spec.md', content_type: 'text/markdown' },
    ],
    outline: [
        { level: 1, text: 'PDF extractor' },
        { level: 2, text: 'When to use' },
        { level: 2, text: 'Steps' },
        { level: 2, text: 'Notes' },
    ],
    version: 4,
    created_by: MOCK_AUTHOR,
    created_at: '2025-01-14T10:00:00Z',
    updated_at: '2025-01-14T10:00:00Z',
    deleted: false,
    is_latest: true,
    latest_version: 4,
    version_count: 4,
    first_version_created_at: '2025-01-11T10:00:00Z',
}

const RESOLVE_RESPONSE: LLMSkillResolveResponseApi = {
    skill: SKILL,
    versions: VERSIONS,
    has_more: false,
}

const SKILL_LIST_ENTRY: LLMSkillListApi = {
    id: SKILL.id,
    name: SKILL.name,
    description: SKILL.description,
    license: SKILL.license,
    compatibility: SKILL.compatibility,
    allowed_tools: SKILL.allowed_tools,
    metadata: {},
    outline: SKILL.outline,
    version: SKILL.version,
    created_by: SKILL.created_by,
    created_at: SKILL.created_at,
    updated_at: SKILL.updated_at,
    deleted: SKILL.deleted,
    is_latest: SKILL.is_latest,
    latest_version: SKILL.latest_version,
    version_count: SKILL.version_count,
    first_version_created_at: SKILL.first_version_created_at,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/LLM Analytics/Skills',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-28',
        pageUrl: urls.llmAnalyticsSkill(SKILL_NAME),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/llm_skills/': toPaginatedResponse([SKILL_LIST_ENTRY]),
                '/api/environments/:team_id/llm_skills/resolve/name/:name/': RESOLVE_RESPONSE,
            },
        }),
    ],
}
export default meta
type Story = StoryObj<{}>

export const SkillDetailStackedBelow2xlBreakpoint: Story = {
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: true,
            viewportWidths: ['medium', 'wide'],
        },
    },
}

export const SkillDetailSideBySideAbove2xlBreakpoint: Story = {
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: true,
            viewportWidths: ['superwide'],
        },
    },
}
