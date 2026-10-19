import { useActions, useValues } from 'kea'

import { IconUnlock } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { MessageTemplateLogicProps, messageTemplateLogic } from './messageTemplateLogic'
import { openReleaseTemplateDialog } from './releaseTemplateDialog'

export function MessageTemplateMenu(props: MessageTemplateLogicProps): JSX.Element {
    const logic = messageTemplateLogic(props)
    const { duplicateTemplate, deleteTemplate, releaseTemplate } = useActions(logic)
    const { originalTemplate, templateChanged, templateLoading, isCodeManaged, isDuplicating } = useValues(logic)
    const { setIsSaveTemplateModalOpen } = useActions(emailTemplaterLogic)

    return (
        <More
            size="small"
            overlay={
                <>
                    {!isCodeManaged && (
                        <LemonButton
                            data-attr="save-as-new-template"
                            fullWidth
                            onClick={() => setIsSaveTemplateModalOpen(true)}
                        >
                            Save as new template
                        </LemonButton>
                    )}
                    {props.id !== 'new' && (
                        <>
                            <LemonButton
                                data-attr="duplicate-message-template"
                                fullWidth
                                onClick={duplicateTemplate}
                                loading={isDuplicating}
                                disabledReason={templateChanged ? 'Save your changes before duplicating' : undefined}
                            >
                                Duplicate
                            </LemonButton>
                            {isCodeManaged && (
                                <LemonButton
                                    data-attr="message-template-release"
                                    icon={<IconUnlock />}
                                    fullWidth
                                    onClick={() => openReleaseTemplateDialog(originalTemplate, releaseTemplate)}
                                    disabledReason={templateLoading ? 'Wait for the template to load' : undefined}
                                >
                                    Stop managing in code
                                </LemonButton>
                            )}
                            <LemonDivider />
                            <LemonButton
                                data-attr="delete-message-template"
                                status="danger"
                                fullWidth
                                onClick={deleteTemplate}
                                disabledReason={
                                    isCodeManaged
                                        ? 'This template is managed by code. To delete it, stop managing it in code first.'
                                        : undefined
                                }
                            >
                                Delete
                            </LemonButton>
                        </>
                    )}
                </>
            }
        />
    )
}
