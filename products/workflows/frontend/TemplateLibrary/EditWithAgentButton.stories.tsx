import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { screen, waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { NEW_TEMPLATE } from './constants'
import { EditWithAgentButton } from './EditWithAgentButton'
import { messageTemplateLogic } from './messageTemplateLogic'
import { MessageTemplate } from './types'

const TEMPLATE_ID = '01a148c7-7912-0000-f7e3-d9ac5081d0c6'

const HOW_IT_GOES_LIVE =
    '- Do not upload the file by hand. If the app sends it with `posthog.emails.templateFile()`, the next send uploads the changed file. If the app sends it by the key `welcome`, upload the file again after the change (PUT /api/projects/@current/messaging_templates/by_key/welcome/ or the PostHog MCP upload tool).\n' +
    `- The template in PostHog: https://us.posthog.com/project/997/workflows/library/templates/${TEMPLATE_ID}`

const FILE_CONTRACT_AND_VARIABLES =
    '- The file is the whole email. The subject is the first `<title>`. The inbox preview text is the `content` of `<meta name="preheader">`. Everything in the file is the HTML that PostHog sends.\n' +
    '- Personalize only with `{{ variables.<name> }}`. The values come from the `data` the app passes to `posthog.emails.send`. This file uses `{{ variables.first_name }}` and `{{ variables.confirm_url }}`.\n'

function codeManagedTemplate(overrides: Partial<MessageTemplate>): MessageTemplate {
    return {
        ...NEW_TEMPLATE,
        id: TEMPLATE_ID,
        name: 'Welcome',
        key: 'welcome',
        managed_by: 'code',
        ...overrides,
    }
}

const WITH_PATH = codeManagedTemplate({
    source_repository: 'github.com/example/app',
    source_path: 'emails/welcome.html',
    source_ref: '9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d',
    change_prompt_starter: 'In `emails/welcome.html`, change ',
    change_prompt_context:
        'About this file:\n' +
        '- It is the PostHog email template with the key `welcome`, in the repository `github.com/example/app`, last uploaded from commit `9e8d7c6`.\n' +
        FILE_CONTRACT_AND_VARIABLES +
        HOW_IT_GOES_LIVE,
})

const WITHOUT_PATH = codeManagedTemplate({
    change_prompt_starter: 'In the HTML file of the `welcome` email template, change ',
    change_prompt_context:
        'About this file:\n' +
        '- Find the HTML file that the app loads with `posthog.emails.templateFile()` for the key `welcome`.\n' +
        FILE_CONTRACT_AND_VARIABLES +
        HOW_IT_GOES_LIVE,
})

type Story = StoryObj<{ template: MessageTemplate }>

const meta: Meta<{ template: MessageTemplate }> = {
    title: 'Products/Workflows/Template library/Edit with your agent',
    parameters: { testOptions: { waitForSelector: '[data-attr="message-template-change-sentence"]' } },
}
export default meta

const OpenAgentPrompt: StoryFn<{ template: MessageTemplate }> = ({ template }) => {
    const logicProps = { id: template.id }
    const { originalTemplate } = useValues(messageTemplateLogic(logicProps))
    const { setAgentPromptOpen } = useActions(messageTemplateLogic(logicProps))
    const loaded = originalTemplate.id === template.id

    useEffect(() => {
        if (loaded) {
            setAgentPromptOpen(true)
        }
    }, [loaded, setAgentPromptOpen])

    return (
        <div className="flex justify-end items-start w-160 h-144 p-2">
            <EditWithAgentButton {...logicProps} />
        </div>
    )
}

const AgentPromptClosed: StoryFn<{ template: MessageTemplate }> = ({ template }) => (
    <div className="flex justify-end items-start w-160 h-48 p-2">
        <EditWithAgentButton id={template.id} />
    </div>
)

function serving(template: MessageTemplate): Story['decorators'] {
    return [mswDecorator({ get: { '/api/environments/:team_id/messaging_templates/:id/': template } })]
}

export const WithAPath: Story = {
    render: OpenAgentPrompt,
    args: { template: WITH_PATH },
    decorators: serving(WITH_PATH),
}

export const WithoutAPath: Story = {
    render: OpenAgentPrompt,
    args: { template: WITHOUT_PATH },
    decorators: serving(WITHOUT_PATH),
}

export const FullPromptShown: Story = {
    render: OpenAgentPrompt,
    args: { template: WITH_PATH },
    decorators: serving(WITH_PATH),
    play: async () => {
        await userEvent.click(await screen.findByText('Show full prompt'))
    },
}

export const CopyMenuOpen: Story = {
    render: AgentPromptClosed,
    args: { template: WITH_PATH },
    decorators: serving(WITH_PATH),
    parameters: { testOptions: { waitForSelector: '[data-attr="message-template-copy-html-file"]' } },
    play: async () => {
        const copyOptions = await waitFor(
            () => {
                const button = screen.getByLabelText('More ways to copy this template')
                if (button.getAttribute('aria-disabled') !== 'false') {
                    throw new Error('The template is still loading')
                }
                return button
            },
            { timeout: 10000 }
        )
        await userEvent.click(copyOptions)
    },
}
