import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { screen } from '@testing-library/dom'
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
    "- Publish only after the change is reviewed and merged, because an upload replaces the published template at once. If the app sends the file with `posthog.emails.templateFile()`, its first send after the release uploads the changed file. If the app sends it by the key `welcome`, run the app's upload code for that key again after the merge, so the subject, preview text and plain-text body go up with the HTML.\n" +
    `- The template in PostHog: https://us.posthog.com/project/997/workflows/library/templates/${TEMPLATE_ID}`

const FILE_CONTRACT_AND_VARIABLES =
    '- If the app loads the file with `posthog.emails.templateFile()`, the file is the whole email: the subject is the first `<title>`, and the inbox preview text is the `content` of `<meta name="preheader">`. If the app uploads it by key, change the subject and preview text where its upload code sets them. PostHog sends the HTML as it is.\n' +
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
        '- `emails/welcome.html` is the PostHog email template with the key `welcome`, in the repository `github.com/example/app`, last uploaded from commit `9e8d7c6`.\n' +
        FILE_CONTRACT_AND_VARIABLES +
        HOW_IT_GOES_LIVE,
})

const WITHOUT_PATH = codeManagedTemplate({
    change_prompt_starter: 'In the HTML file of the `welcome` email template, change ',
    change_prompt_context:
        'About this file:\n' +
        '- Find the HTML file of the email template with the key `welcome`. The app loads it with `posthog.emails.templateFile()` or uploads it by that key.\n' +
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
