import { MOCK_USER_UUID } from 'lib/api.mock'

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
} from 'products/skills/frontend/generated/api.schemas'

// Matches the mocked organization member, so the owner picker resolves it to a name rather than
// falling back to the raw UUID.
const MOCK_AUTHOR: UserBasicApi = {
    id: 178,
    uuid: MOCK_USER_UUID,
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
        version_description: version === 4 ? 'Added OCR guidance for scanned PDFs' : null,
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
    body_total_length: SKILL_BODY.length,
    body_next_offset: null,
    license: 'Apache-2.0',
    compatibility: 'Requires poppler-utils on the host',
    allowed_tools: ['read', 'shell'],
    metadata: {},
    category: '',
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
    version_description: 'Added OCR guidance for scanned PDFs',
    created_by: MOCK_AUTHOR,
    owners: [MOCK_AUTHOR],
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
    category: SKILL.category,
    outline: SKILL.outline,
    version: SKILL.version,
    version_description: SKILL.version_description,
    created_by: SKILL.created_by,
    owners: SKILL.owners,
    created_at: SKILL.created_at,
    updated_at: SKILL.updated_at,
    deleted: SKILL.deleted,
    is_latest: SKILL.is_latest,
    latest_version: SKILL.latest_version,
    version_count: SKILL.version_count,
    first_version_created_at: SKILL.first_version_created_at,
}

const UNOWNED_SKILL_LIST_ENTRY: LLMSkillListApi = {
    ...SKILL_LIST_ENTRY,
    id: 'skill-version-9',
    name: 'invoice-parser',
    description: 'Parse invoices into structured line items. Use when reconciling billing exports.',
    owners: [],
    version_count: 1,
    version: 1,
    latest_version: 1,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/AI observability/Skills',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-28',
        pageUrl: urls.skill(SKILL_NAME),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/llm_skills/': toPaginatedResponse([SKILL_LIST_ENTRY, UNOWNED_SKILL_LIST_ENTRY]),
                '/api/projects/:team_id/llm_skills/resolve/name/:name/': RESOLVE_RESPONSE,
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

export const SkillsList: Story = {
    parameters: {
        pageUrl: urls.skills(),
    },
}
