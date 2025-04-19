import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { EmailTemplater } from 'scenes/pipeline/hogfunctions/email-templater/EmailTemplater'
import { SceneExport } from 'scenes/sceneTypes'

import { templateLogic, TemplateLogicProps } from './templateLogic'

export const scene: SceneExport = {
    component: Template,
    logic: templateLogic,
    paramsToProps: ({ params: { id }, searchParams: { messageId } }): (typeof templateLogic)['props'] => ({
        id: id || 'new',
        messageId,
    }),
}

export function Template({ id }: TemplateLogicProps = {}): JSX.Element {
    const { submitTemplate, resetTemplate } = useActions(templateLogic)
    const { originalTemplate, isTemplateSubmitting, templateChanged } = useValues(templateLogic)

    return (
        <div className="space-y-4">
            <Form logic={templateLogic} formKey="template">
                <PageHeader
                    buttons={
                        <div className="flex items-center gap-2">
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
                        </div>
                    }
                />
                <div className="flex flex-wrap gap-4 items-start">
                    <div className="space-y-2 flex-1 min-w-100 p-3 bg-surface-primary border rounded self-start">
                        <LemonField name="name" label="Name">
                            <LemonInput />
                        </LemonField>

                        <LemonField
                            name="description"
                            label="Description"
                            info="Add a description to share context with other team members"
                        >
                            <LemonTextArea />
                        </LemonField>
                    </div>

                    <div className="flex-2 min-w-100 space-y-2 p-3 bg-surface-primary border rounded">
                        <h3>Email template</h3>
                        <EmailTemplater
                            formLogic={templateLogic}
                            formLogicProps={{ id }}
                            formKey="template"
                            formFieldsPrefix="content.email"
                            emailMetaFields={['from', 'subject']}
                        />
                    </div>
                </div>
            </Form>
        </div>
    )
}
