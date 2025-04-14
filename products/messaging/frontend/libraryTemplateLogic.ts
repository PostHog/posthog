import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { EmailTemplate } from 'scenes/pipeline/hogfunctions/email-templater/emailTemplaterLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { libraryTemplateLogicType } from './libraryTemplateLogicType'

type LibraryEmailTemplate = Omit<EmailTemplate, 'to'>

const NEW_TEMPLATE: LibraryEmailTemplate = {
    html: '<html><head></head><body><p>Your email content here</p></body></html>',
    subject: 'New email subject',
    text: 'Your plain text email content here',
    from: 'notifications@yourdomain.com',
    design: JSON.stringify({
        body: {
            rows: [],
            values: {
                backgroundColor: '#ff0000',
                width: '600px',
                padding: '0px',
            },
        },
    }),
}

export interface LibraryTemplateLogicProps {
    logicKey?: string
    id?: string | null
}

export const libraryTemplateLogic = kea<libraryTemplateLogicType>([
    path(['products', 'messaging', 'frontend', 'libraryTemplateLogic']),
    props({} as LibraryTemplateLogicProps),
    key(({ id }) => id ?? 'unknown'),
    actions({
        setTemplate: (template: LibraryEmailTemplate) => ({ template }),
    }),
    reducers({
        template: [
            NEW_TEMPLATE,
            {
                setTemplate: (_, { template }) => {
                    return template
                },
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            () => [(_, props) => props],
            (props: LibraryTemplateLogicProps): Breadcrumb[] => {
                const { id } = props

                if (!id) {
                    return []
                }

                return [
                    {
                        key: Scene.MessagingLibrary,
                        name: 'Messaging',
                        path: urls.messagingLibrary(),
                    },
                    {
                        key: 'library',
                        name: 'Library',
                        path: urls.messagingLibrary(),
                    },
                    ...(id === 'new'
                        ? [
                              {
                                  key: 'new-template',
                                  name: 'New template',
                                  path: urls.messagingLibraryTemplateNew(),
                              },
                          ]
                        : [
                              {
                                  key: 'edit-template',
                                  name: 'Manage template',
                                  path: urls.messagingLibraryTemplate(id),
                              },
                          ]),
                ]
            },
        ],
        logicProps: [
            () => [(_, props) => props],
            (props: LibraryTemplateLogicProps): LibraryTemplateLogicProps => props,
        ],
        globalsWithInputs: [
            () => [],
            () => {
                return {
                    project: {
                        id: 0,
                        name: 'Default project',
                    },
                    event: {
                        uuid: '',
                        event: '$pageview',
                        properties: {},
                    },
                    person: {
                        id: '',
                        properties: {
                            email: 'user@example.com',
                        },
                    },
                    inputs: {
                        html: 'string',
                        subject: 'string',
                        text: 'string',
                        from: 'string',
                        to: 'string',
                    },
                }
            },
        ],
    }),
    forms({
        emailTemplate: {
            defaults: {
                html: '',
                subject: '',
                text: '',
                from: '',
            } as LibraryEmailTemplate,
            errors: (values: LibraryEmailTemplate) => ({
                html: !values.html ? 'HTML is required' : undefined,
                subject: !values.subject ? 'Subject is required' : undefined,
                from: !values.from ? 'From is required' : undefined,
            }),
            submit: async (values: LibraryEmailTemplate) => {
                // Here you would typically submit the form data to an API

                // eslint-disable-next-line no-console
                console.log('Submitting email template:', values)
                // Example: await api.emailTemplates.create(values)
            },
        },
    }),
])
