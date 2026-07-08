import { Meta } from '@storybook/react'

import { LemonCard } from '@posthog/lemon-ui'

import { sceneLogic } from 'scenes/sceneLogic'

import { mswDecorator } from '~/mocks/browser'
import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { ExceptionLogicWrapper } from '../../../../__mocks__/events'
import { results as batchGetResults } from '../../../../__mocks__/stack_frames/batch_get'
import { StyleVariables } from '../../../StyleVariables'
import { StackTraceActions } from './StackTraceActions'

const MOCK_ISSUE: ErrorTrackingRelationalIssue = {
    id: 'issue-id',
    name: 'Test issue',
    description: null,
    assignee: null,
    status: 'active',
    first_seen: '2024-01-01T00:00:00Z',
}

const meta: Meta = {
    title: 'ErrorTracking/StackTraceActions',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    decorators: [
        (Story: React.FC): JSX.Element => {
            sceneLogic.mount()
            return (
                <StyleVariables>
                    <LemonCard hoverEffect={false} className="p-2">
                        <Story />
                    </LemonCard>
                </StyleVariables>
            )
        },
        mswDecorator({
            post: {
                'api/environments/:team_id/error_tracking/stack_frames/batch_get/': { results: batchGetResults },
            },
        }),
    ],
}

export default meta

export function Default(): JSX.Element {
    return (
        <ExceptionLogicWrapper eventName="javascript_resolved">
            <StackTraceActions issue={MOCK_ISSUE} />
        </ExceptionLogicWrapper>
    )
}
