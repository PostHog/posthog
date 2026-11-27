import type { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { AEOPromptTopicApi } from '../generated/api.schemas'
import { type TopicChangeKind, aiVisibilityTopicsLogic } from './aiVisibilityTopicsLogic'
import { AiVisibilityTopicsSetting } from './AiVisibilityTopicsSetting'

const TOPICS: AEOPromptTopicApi[] = [
    { topic: '', prompts: 3 },
    { topic: 'File sharing', prompts: 6 },
    { topic: 'file-sharing', prompts: 1 },
    { topic: 'Pricing', prompts: 4 },
    { topic: 'Security', prompts: 2 },
]

const meta: Meta<typeof AiVisibilityTopicsSetting> = {
    title: 'Products/Web Analytics/Content autopilot/Topics setting',
    component: AiVisibilityTopicsSetting,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/aeo_prompts/topics/': () => [200, TOPICS] },
        }),
    ],
}

export default meta

const TopicsStory = ({ dialog }: { dialog?: TopicChangeKind }): JSX.Element => {
    const { openTopicDialog } = useActions(aiVisibilityTopicsLogic)
    useEffect(() => {
        if (dialog) {
            openTopicDialog(dialog, 'file-sharing')
        }
    }, [dialog, openTopicDialog])
    return (
        <div className="p-4 max-w-200" data-quill>
            <AiVisibilityTopicsSetting />
        </div>
    )
}

export const Topics: StoryFn<typeof AiVisibilityTopicsSetting> = () => <TopicsStory />

export const MergeTopic: StoryFn<typeof AiVisibilityTopicsSetting> = () => <TopicsStory dialog="merge" />

export const RemoveTopic: StoryFn<typeof AiVisibilityTopicsSetting> = () => <TopicsStory dialog="remove" />
