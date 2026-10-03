import type { Meta, StoryFn } from '@storybook/react'
import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { useStorybookMocks } from '~/mocks/browser'

import type { EmailBrandStarterDesignApi } from '../generated/api.schemas'
import { EmailBrandEntryPoint } from './EmailBrandEntryPoint'
import { EmailBrandFlow } from './EmailBrandFlow'
import { emailBrandFlowLogic } from './emailBrandFlowLogic'
import { exampleBrand, exampleDetection, exampleSuggestions } from './fixtures'

const starter = (name: string, primaryColor: string): EmailBrandStarterDesignApi => ({
    name: `${name} starter template`,
    description: 'Created from your Email brand.',
    subject: `Welcome to ${name}`,
    design: {
        schemaVersion: 16,
        body: {
            rows: [
                {
                    columns: [
                        {
                            contents: [
                                { id: 'brand-starter-name', type: 'heading', values: { text: name } },
                                {
                                    id: 'brand-starter-heading',
                                    type: 'heading',
                                    values: { text: "Hi {{ person.properties.first_name | default: 'there' }}" },
                                },
                                {
                                    id: 'brand-starter-body-text',
                                    type: 'text',
                                    values: {
                                        text: '<p>Write your message here. Keep it short and lead with what the reader gets.</p>',
                                    },
                                },
                                {
                                    id: 'brand-starter-cta',
                                    type: 'button',
                                    values: {
                                        text: '<span>Get started</span>',
                                        buttonColors: { color: primaryColor === '#ffffff' ? '#000000' : '#ffffff' },
                                    },
                                },
                                {
                                    id: 'brand-starter-unsubscribe',
                                    type: 'custom',
                                    values: {
                                        unsubscribe_link_content:
                                            '<p>You received this email from Juniper. Unsubscribe</p>',
                                    },
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    },
})

const onComplete = (): void => {}
const props = { entryPoint: 'template_library' as const, onComplete }
type Scenario =
    | 'interactive'
    | 'connect'
    | 'review'
    | 'app'
    | 'files'
    | 'detecting'
    | 'empty'
    | 'conflicts'
    | 'disconnected'
    | 'busy'
    | 'logo'
    | 'editor'

function FlowStory({ scenario }: { scenario: Scenario }): JSX.Element {
    const suggestionReads = useRef(0)
    useStorybookMocks({
        get: {
            '/api/projects/:id/email_brand/current/': ['review', 'editor'].includes(scenario)
                ? exampleBrand
                : () => [404, { detail: 'No Email brand yet.' }],
            '/api/projects/:id/email_brand/suggest_repository/': () =>
                scenario === 'connect' || (scenario === 'interactive' && suggestionReads.current++ === 0)
                    ? { integration_id: null, repositories: [] }
                    : exampleSuggestions,
            '/api/projects/:id/integrations/': { results: [{ id: 7, kind: 'github', config: {}, errors: [] }] },
            '/api/projects/:id/integrations/:integration_id/repos/': { repositories: exampleSuggestions.repositories },
        },
        post: {
            '/api/projects/:id/email_brand/detect/':
                scenario === 'detecting'
                    ? () => new Promise(() => {})
                    : scenario === 'disconnected' || scenario === 'busy'
                      ? () => [
                            scenario === 'busy' ? 429 : 400,
                            {
                                code: scenario === 'busy' ? 'github_busy' : 'github_disconnected',
                                detail: 'GitHub could not finish this request.',
                            },
                        ]
                      : scenario === 'empty'
                        ? {
                              ...exampleDetection,
                              proposal: {
                                  name: null,
                                  primary_color: null,
                                  accent_color: null,
                                  text_color: null,
                                  background_color: null,
                                  font_family: null,
                              },
                          }
                        : scenario === 'app'
                          ? { ...exampleDetection, app_root: 'apps/web', app_root_alternatives: ['apps/admin'] }
                          : scenario === 'logo'
                            ? {
                                  ...exampleDetection,
                                  logo_candidates: [{ path: 'public/logo.png', width: 320, height: 120 }],
                              }
                            : exampleDetection,
            '/api/projects/:id/email_brand/preview_starter_design/': async ({ request }) => {
                const brand = (await request.json()) as { name: string; primary_color: string }
                return starter(brand.name || 'Your brand', brand.primary_color)
            },
            '/api/projects/:id/email_brand/import_logo/': {
                outcome: 'imported',
                media_id: '00000000-0000-4000-8000-000000000210',
                url: 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22320%22 height=%22120%22%3E%3Crect width=%22320%22 height=%22120%22 fill=%22%23276749%22/%3E%3C/svg%3E',
                svg: null,
            },
            '/api/projects/:id/uploaded_media/': {
                id: '00000000-0000-4000-8000-000000000211',
                image_location:
                    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aA1cAAAAASUVORK5CYII=',
            },
            '/api/projects/:id/email_brand/create_starter_template/': () =>
                scenario === 'editor'
                    ? [422, { code: 'design_rendering_unavailable', detail: 'Open the editor.' }]
                    : [201, { template_id: '00000000-0000-4000-8000-000000000209' }],
        },
        patch: {
            '/api/projects/:id/email_brand/current/': async ({ request }) => ({
                ...exampleBrand,
                ...((await request.json()) as object),
            }),
        },
    })
    const logic = emailBrandFlowLogic(props)
    const { initial, step } = useValues(logic)
    const started = useRef(false)
    const reviewed = useRef(false)
    useEffect(() => {
        if (initial && !started.current && !['interactive', 'connect', 'review', 'editor'].includes(scenario)) {
            started.current = true
            logic.actions.detect()
        }
        if (step === 'files' && !reviewed.current && ['conflicts', 'empty', 'logo'].includes(scenario)) {
            reviewed.current = true
            logic.actions.reviewDetection()
            if (scenario === 'conflicts') {
                logic.actions.editField('primary_color', '#ff5500')
                logic.actions.detect(true)
            }
        } else if (step === 'files' && reviewed.current && scenario === 'conflicts') {
            logic.actions.reviewDetection()
        }
    }, [initial, step, logic, scenario])
    return (
        <div className="p-4">
            <EmailBrandFlow {...props} />
        </div>
    )
}

const meta: Meta = {
    title: 'Products/Workflows/EmailBrandFlow',
    component: EmailBrandFlow,
    parameters: { layout: 'fullscreen', featureFlags: ['workflows-brand-detection'] },
}
export default meta
const Template: StoryFn<{ scenario: Scenario }> = (args) => <FlowStory {...args} />
export const Interactive = Template.bind({})
Interactive.args = { scenario: 'interactive' }
export const Connect = Template.bind({})
Connect.args = { scenario: 'connect' }
export const Review = Template.bind({})
Review.args = { scenario: 'review' }
export const AppSelection = Template.bind({})
AppSelection.args = { scenario: 'app' }
export const FileReplay = Template.bind({})
FileReplay.args = { scenario: 'files' }
export const Detecting = Template.bind({})
Detecting.args = { scenario: 'detecting' }
export const NothingFound = Template.bind({})
NothingFound.args = { scenario: 'empty' }
export const Conflicts = Template.bind({})
Conflicts.args = { scenario: 'conflicts' }
export const GitHubDisconnected = Template.bind({})
GitHubDisconnected.args = { scenario: 'disconnected' }
export const GitHubBusy = Template.bind({})
GitHubBusy.args = { scenario: 'busy' }
export const LogoChoices = Template.bind({})
LogoChoices.args = { scenario: 'logo' }
export const EditorFallback = Template.bind({})
EditorFallback.args = { scenario: 'editor' }
export const ChannelsEntry = (): JSX.Element => {
    useStorybookMocks({ get: { '/api/projects/:id/email_brand/current/': exampleBrand } })
    return (
        <div className="p-4">
            <EmailBrandEntryPoint entryPoint="channels" />
        </div>
    )
}
export const LibraryEntry = (): JSX.Element => (
    <div className="p-4">
        <EmailBrandEntryPoint entryPoint="template_library" />
    </div>
)
export const FlagOff = (): JSX.Element => (
    <div>
        <EmailBrandEntryPoint entryPoint="channels" />
        <EmailBrandEntryPoint entryPoint="template_library" />
        <EmailBrandFlow {...props} />
    </div>
)
FlagOff.parameters = { featureFlags: { 'workflows-brand-detection': false } }
