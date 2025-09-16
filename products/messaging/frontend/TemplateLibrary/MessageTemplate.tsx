import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCode } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTextArea, Spinner, Tooltip } from '@posthog/lemon-ui'

import { PageHeader } from 'lib/components/PageHeader'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { EmailTemplater } from 'scenes/hog-functions/email-templater/EmailTemplater'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { MessageTemplateLogicProps, messageTemplateLogic } from './messageTemplateLogic'

export const scene: SceneExport<MessageTemplateLogicProps> = {
    component: MessageTemplate,
    logic: messageTemplateLogic,
    paramsToProps: ({ params: { id }, searchParams: { messageId } }) => ({
        id: id || 'new',
        messageId,
    }),
}

export function MessageTemplate({ id }: MessageTemplateLogicProps): JSX.Element {
    const { submitTemplate, resetTemplate, setTemplateValue } = useActions(messageTemplateLogic)
    const { template, originalTemplate, isTemplateSubmitting, templateChanged, messageLoading } =
        useValues(messageTemplateLogic)

    return (
        <SceneContent>
            <Form logic={messageTemplateLogic} formKey="template" className="flex flex-col gap-4">
                <PageHeader
                    buttons={
                        <>
                            {templateChanged && (
                                <LemonButton
                                    data-attr="cancel-message-template"
                                    type="secondary"
                                    onClick={() => resetTemplate(originalTemplate)}
                                >
                                    Discard changes
                                </LemonButton>
                            )}
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                form="template"
                                onClick={submitTemplate}
                                loading={isTemplateSubmitting}
                                disabledReason={templateChanged ? undefined : 'No changes to save'}
                            >
                                {id === 'new' ? 'Create' : 'Save'}
                            </LemonButton>
                        </>
                    }
                />
                <SceneTitleSection name={template.name} resourceType={{ type: 'template' }} />

                <div className="flex flex-wrap gap-4 items-start">
                    <div className="flex-1 self-start p-3 space-y-2 rounded border min-w-100 bg-surface-primary">
                        <LemonField name="name" label="Name">
                            <LemonInput disabled={messageLoading} />
                        </LemonField>

                        <LemonField
                            name="description"
                            label="Description"
                            info="Add a description to share context with other team members"
                        >
                            <LemonTextArea disabled={messageLoading} />
                        </LemonField>
                    </div>

                    <div className="p-3 space-y-2 rounded border flex-2 min-w-100 bg-surface-primary">
                        <div className="flex justify-between items-center">
                            <h3>Email template</h3>
                            <Tooltip
                                title="You can use Liquid templating in any email text field."
                                docLink="https://liquidjs.com/filters/overview.html"
                            >
                                <span>
                                    <IconCode fontSize={24} />
                                </span>
                            </Tooltip>
                        </div>
                        {messageLoading ? (
                            <Spinner className="text-lg" />
                        ) : (
                            <EmailTemplater
                                value={template?.content.email}
                                onChange={(value) => setTemplateValue('content.email', value)}
                                onChangeTemplating={(templating) =>
                                    setTemplateValue('content.email.templating', templating)
                                }
                                type="native_email_template"
                            />
                        )}
                    </div>
                </div>
            </Form>
        </SceneContent>
    )
}
