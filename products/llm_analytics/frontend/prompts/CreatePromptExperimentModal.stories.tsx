import { MOCK_DEFAULT_BASIC_USER } from '~/lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'
import { LLMPromptVersionSummary } from '~/types'

import { CreatePromptExperimentModal } from './CreatePromptExperimentModal'
import { createPromptExperimentModalLogic } from './createPromptExperimentModalLogic'

const PROMPT_NAME = 'storybook-prompt'

const MOCK_VERSIONS: LLMPromptVersionSummary[] = [
    { id: 'v5', version: 5, created_by: MOCK_DEFAULT_BASIC_USER, created_at: '2025-01-15T10:00:00Z', is_latest: true },
    {
        id: 'v4',
        version: 4,
        created_by: MOCK_DEFAULT_BASIC_USER,
        created_at: '2025-01-12T10:00:00Z',
        is_latest: false,
    },
    {
        id: 'v3',
        version: 3,
        created_by: MOCK_DEFAULT_BASIC_USER,
        created_at: '2025-01-10T10:00:00Z',
        is_latest: false,
    },
    {
        id: 'v2',
        version: 2,
        created_by: MOCK_DEFAULT_BASIC_USER,
        created_at: '2025-01-05T10:00:00Z',
        is_latest: false,
    },
    {
        id: 'v1',
        version: 1,
        created_by: MOCK_DEFAULT_BASIC_USER,
        created_at: '2025-01-01T10:00:00Z',
        is_latest: false,
    },
]

function OpenCreatePromptExperimentModal(): JSX.Element {
    const { openModal } = useActions(createPromptExperimentModalLogic)
    useEffect(() => {
        openModal(PROMPT_NAME, MOCK_VERSIONS)
    }, [openModal])
    return <CreatePromptExperimentModal />
}

const MOCK_TEMPLATES = [
    { key: 'cost', label: 'Cost', description: 'Compares total $ai_total_cost_usd between prompt versions.' },
    { key: 'latency', label: 'Latency', description: 'Compares total $ai_latency between prompt versions.' },
    {
        key: 'eval_pass_rate',
        label: 'Eval pass rate',
        description: 'Ratio of passing $ai_evaluation events for this prompt.',
    },
]

type Story = StoryObj<typeof CreatePromptExperimentModal>
const meta: Meta<typeof CreatePromptExperimentModal> = {
    title: 'AI observability/Create prompt experiment modal',
    component: CreatePromptExperimentModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-28',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:project_id/experiments/prompt_templates/': () => [200, MOCK_TEMPLATES],
            },
        }),
    ],
    render: () => <OpenCreatePromptExperimentModal />,
}

export default meta

export const Default: Story = {}
