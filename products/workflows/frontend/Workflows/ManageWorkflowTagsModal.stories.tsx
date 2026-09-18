import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import type { TagApi } from '~/generated/core/api.schemas'
import { useStorybookMocks } from '~/mocks/browser'

import { ManageWorkflowTagsModal } from './ManageWorkflowTagsModal'
import { workflowTagsLogic } from './workflowTagsLogic'

const pinnedTags: TagApi[] = [
    { id: 'tag-1', name: 'marketing', pinned: true },
    { id: 'tag-2', name: 'onboarding', pinned: true },
    { id: 'tag-3', name: 'retention', pinned: true },
]

const meta: Meta = {
    title: 'Products/Workflows/ManageWorkflowTagsModal',
    component: ManageWorkflowTagsModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

type StoryProps = {
    tags: TagApi[]
}

const Template: StoryFn<StoryProps> = ({ tags }) => {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/tags/pinned/': tags,
        },
    })
    const { openManageTagsModal, loadPinnedTags } = useActions(workflowTagsLogic)

    useEffect(() => {
        loadPinnedTags()
        openManageTagsModal()
    }, [loadPinnedTags, openManageTagsModal])

    return <ManageWorkflowTagsModal />
}

export const WithTags: StoryFn<StoryProps> = Template.bind({})
WithTags.args = { tags: pinnedTags }
WithTags.parameters = { testOptions: { waitForSelector: '.LemonTag' } }

export const NoTagsYet: StoryFn<StoryProps> = Template.bind({})
NoTagsYet.args = { tags: [] }
NoTagsYet.parameters = { testOptions: { waitForSelector: '.LemonModal__content' } }
