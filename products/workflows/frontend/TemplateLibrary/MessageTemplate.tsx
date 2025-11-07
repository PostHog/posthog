import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCode } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonTextArea, Spinner, Tooltip } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { EmailTemplater } from 'scenes/hog-functions/email-templater/EmailTemplater'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
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
    const { submitTemplate, resetTemplate, setTemplateValue, duplicateTemplate, deleteTemplate } =
        useActions(messageTemplateLogic)
    const { template, originalTemplate, isTemplateSubmitting, templateChanged, messageLoading } =
        useValues(messageTemplateLogic)

    return (
        <Form logic={messageTemplateLogic} formKey="template">
            <SceneContent>
                <SceneTitleSection
                    name={template.name}
                    resourceType={{ type: 'template' }}
                    actions={
                        <>
                            {id !== 'new' && (
                                <>
                                    <More
                                        size="small"
                                        overlay={
                                            <>
                                                <LemonButton
                                                    data-attr="duplicate-message-template"
                                                    fullWidth
                                                    onClick={duplicateTemplate}
                                                    disabledReason={
                                                        templateChanged
                                                            ? 'Save your changes before duplicating'
                                                            : undefined
                                                    }
                                                >
                                                    Duplicate
                                                </LemonButton>
                                                <LemonDivider />
                                                <LemonButton
                                                    data-attr="delete-message-template"
                                                    status="danger"
                                                    fullWidth
                                                    onClick={deleteTemplate}
                                                >
                                                    Delete
                                                </LemonButton>
                                            </>
                                        }
                                    />
                                    <LemonDivider vertical />
                                </>
                            )}
                            {templateChanged && (
                                <LemonButton
                                    data-attr="cancel-message-template"
                                    type="secondary"
                                    onClick={() => resetTemplate(originalTemplate)}
                                    size="small"
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
                                size="small"
                            >
                                {id === 'new' ? 'Create' : 'Save'}
                            </LemonButton>
                        </>
                    }
                />
                <SceneDivider />

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
            </SceneContent>
        </Form>
    )
}
