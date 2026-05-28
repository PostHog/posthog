import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FilterChips } from './FilterChips'

const meta: Meta<typeof FilterChips> = {
    title: 'Console/FilterChips',
    component: FilterChips,
    parameters: { layout: 'centered' },
}

export default meta

const AGENT_FILTERS = ['all', 'live', 'drafts', 'archived'] as const

export const AgentList: StoryObj = {
    render: () => {
        const [value, setValue] = useState<(typeof AGENT_FILTERS)[number]>('all')
        return <FilterChips options={AGENT_FILTERS} value={value} onChange={setValue} />
    },
}

const SESSION_FILTERS = ['all', 'streaming', 'awaiting-approval', 'errored'] as const

export const SessionsList: StoryObj = {
    render: () => {
        const [value, setValue] = useState<(typeof SESSION_FILTERS)[number]>('all')
        return <FilterChips options={SESSION_FILTERS} value={value} onChange={setValue} />
    },
}
