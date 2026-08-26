import './MessageTemplatesGrid.scss'

import { Meta } from '@storybook/react'

import { IconTrash } from '@posthog/icons'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import { UserBasicType } from '~/types'

import type { HogFlowTemplate } from '../Workflows/hogflows/types'
import { MessageTemplateCard } from './MessageTemplateCard'
import type { MessageTemplate } from './types'
import { WorkflowTemplateCard } from './WorkflowTemplateCard'

const meta: Meta = {
    title: 'Products/Workflows/Template library cards',
}
export default meta

const createdBy = {
    id: 1,
    uuid: '01890000-0000-0000-0000-000000000001',
    distinct_id: 'sam',
    first_name: 'Sam',
    email: 'sam@example.com',
} as UserBasicType

const emailTemplate: MessageTemplate = {
    id: '01890000-0000-0000-0000-0000000000e1',
    name: 'Welcome email',
    description: 'Sent the day someone signs up',
    type: 'email',
    content: {
        templating: 'liquid',
        email: {
            design: null,
            html: '<h1>Welcome aboard</h1>',
            subject: 'Welcome',
            text: 'Welcome aboard',
            from: 'hello@example.com',
            to: '{{ person.properties.email }}',
        },
    },
    created_at: '2026-08-10T10:00:00Z',
    updated_at: null,
    created_by: createdBy,
}

const webhookTemplate: MessageTemplate = {
    id: '01890000-0000-0000-0000-0000000000f1',
    name: 'Notify billing',
    description: 'Posts the signup to the billing service',
    type: 'function',
    content: {
        templating: 'liquid',
        function: {
            template_id: 'template-webhook',
            inputs: {
                url: { value: 'https://example.com/hooks/billing' },
                method: { value: 'POST' },
            },
        },
    },
    created_at: '2026-08-11T10:00:00Z',
    updated_at: null,
    created_by: createdBy,
}

const teamWorkflowTemplate = {
    id: '01890000-0000-0000-0000-0000000000c1',
    name: 'Trial nurture',
    description: 'Five emails over the first two weeks of a trial',
    tags: ['onboarding'],
    scope: 'team',
    image_url: null,
    created_at: '2026-08-12T10:00:00Z',
    created_by: createdBy,
} as HogFlowTemplate

const orgWorkflowTemplate = {
    ...teamWorkflowTemplate,
    id: '01890000-0000-0000-0000-0000000000c2',
    name: 'Win-back sequence',
    description: 'Re-engages accounts that went quiet for 30 days',
    tags: [],
    scope: 'organization',
    created_at: '2026-08-09T10:00:00Z',
} as HogFlowTemplate

const cardActions = (
    <More
        size="small"
        overlay={
            <LemonMenuOverlay
                items={[{ label: 'Delete', status: 'danger' as const, icon: <IconTrash />, onClick: () => {} }]}
            />
        }
    />
)

/** The library grid holds all three kinds at once, newest first. */
export function AllTemplateKinds(): JSX.Element {
    return (
        <div className="MessageTemplatesGrid">
            <WorkflowTemplateCard template={teamWorkflowTemplate} index={0} onClick={() => {}} actions={cardActions} />
            <MessageTemplateCard template={webhookTemplate} index={1} onClick={() => {}} actions={cardActions} />
            <MessageTemplateCard template={emailTemplate} index={2} onClick={() => {}} actions={cardActions} />
            <WorkflowTemplateCard template={orgWorkflowTemplate} index={3} onClick={() => {}} actions={cardActions} />
        </div>
    )
}
