import { LemonButton, LemonInput, LemonTextArea, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { EmailTemplater } from 'scenes/pipeline/hogfunctions/email-templater/EmailTemplater'
import { SceneExport } from 'scenes/sceneTypes'

import { messageTemplateLogic, MessageTemplateLogicProps } from './messageTemplateLogic'

export const scene: SceneExport = {
    component: MessageTemplate,
    logic: messageTemplateLogic,
    paramsToProps: ({ params: { id }, searchParams: { messageId } }): MessageTemplateLogicProps => ({
        id: id || 'new',
        messageId,
    }),
}

export function MessageTemplate({ id }: MessageTemplateLogicProps = {}): JSX.Element {
    const { submitTemplate, resetTemplate } = useActions(messageTemplateLogic)
    const { originalTemplate, isTemplateSubmitting, templateChanged, messageLoading } = useValues(messageTemplateLogic)

    return (
        <div className="space-y-4">
            <Form logic={messageTemplateLogic} formKey="template">
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
                <div className="flex flex-wrap gap-4 items-start">
                    <div className="space-y-2 flex-1 min-w-100 p-3 bg-surface-primary border rounded self-start">
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

                    <div className="flex-2 min-w-100 space-y-2 p-3 bg-surface-primary border rounded">
                        <h3>Email template</h3>
                        {messageLoading ? (
                            <Spinner className="text-lg" />
                        ) : (
                            <EmailTemplater
                                formLogic={messageTemplateLogic}
                                formLogicProps={{ id }}
                                formKey="template"
                                formFieldsPrefix="content.email"
                                emailMetaFields={['from', 'subject']}
                            />
                        )}
                    </div>
                </div>
            </Form>
        </div>
    )
}
