import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { NEW_TEMPLATE } from './constants'
import { messageTemplateLogic } from './messageTemplateLogic'
import { QuillEditWithAgentButton } from './QuillEditWithAgentButton'
import { MessageTemplate } from './types'

const TEMPLATE: MessageTemplate = {
    ...NEW_TEMPLATE,
    id: '01a148c7-7912-0000-f7e3-d9ac5081d0c7',
    name: 'Welcome',
    key: 'welcome',
    managed_by: 'code',
    source_repository: 'github.com/example/app',
    source_path: 'emails/welcome.html',
    change_prompt_starter: 'In `emails/welcome.html`, change ',
    change_prompt_context:
        'About this file:\n' +
        '- `emails/welcome.html` is the PostHog email template with the key `welcome`, in the repository `github.com/example/app`.\n' +
        '- Personalize only with `{{ variables.<name> }}`. This file uses `{{ variables.first_name }}`.',
}

const meta: Meta = {
    title: 'Products/Workflows/Template library/Edit with your agent (quill)',
    decorators: [mswDecorator({ get: { '/api/environments/:team_id/messaging_templates/:id/': TEMPLATE } })],
    parameters: {
        testOptions: {
            waitForSelector: '[data-attr="message-template-change-sentence"]',
            snapshotBrowsers: [],
        },
    },
}
export default meta

const OpenAgentPrompt: StoryFn = () => {
    const logicProps = { id: TEMPLATE.id }
    const { originalTemplate } = useValues(messageTemplateLogic(logicProps))
    const { setAgentPromptOpen } = useActions(messageTemplateLogic(logicProps))
    const loaded = originalTemplate.id === TEMPLATE.id

    useEffect(() => {
        if (loaded) {
            setAgentPromptOpen(true)
        }
    }, [loaded, setAgentPromptOpen])

    return (
        <div data-quill className="flex justify-end items-start w-160 h-96 p-2">
            <QuillEditWithAgentButton {...logicProps} />
        </div>
    )
}

export const PromptOpen: StoryObj = { render: OpenAgentPrompt }
