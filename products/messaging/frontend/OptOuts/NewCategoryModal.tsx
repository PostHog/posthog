import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTextArea, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { newCategoryLogic } from './newCategoryLogic'

interface MessageCategory {
    id: string
    key: string
    name: string
    description: string
    public_description: string
    category_type: string
}

interface NewCategoryModalProps {
    isOpen: boolean
    onClose: () => void
    category?: MessageCategory | null
}

export function NewCategoryModal({ isOpen, onClose, category }: NewCategoryModalProps): JSX.Element {
    const logic = newCategoryLogic({ category, onSuccess: onClose })
    const { isCategoryFormSubmitting } = useValues(logic)
    const { submitCategoryForm, resetCategoryForm } = useActions(logic)

    const handleClose = (): void => {
        resetCategoryForm()
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            title={category ? 'Edit message category' : 'New message category'}
            footer={
                <div className="flex gap-2 justify-end">
                    <LemonButton type="secondary" onClick={handleClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" loading={isCategoryFormSubmitting} onClick={submitCategoryForm}>
                        {category ? 'Update' : 'Create'}
                    </LemonButton>
                </div>
            }
        >
            <Form
                logic={newCategoryLogic}
                formKey="categoryForm"
                props={{ category, onSuccess: onClose }}
                className="space-y-4"
            >
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="e.g., Product updates" />
                </LemonField>

                <LemonField name="key" label="Key" info="This is the unique identifier for the category">
                    <LemonInput
                        placeholder="e.g., product_updates"
                        disabledReason={category ? 'Key cannot be changed after creation' : undefined}
                    />
                </LemonField>

                <LemonField
                    name="category_type"
                    label="Message type"
                    info="Marketing messages can be opted out of by users. Transactional messages are not affected by recipient preferences"
                    help={
                        <p>
                            Be sure to comply with local regulations regarding marketing communications (
                            <Link
                                to="https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business"
                                target="_blank"
                            >
                                CAN-SPAM
                            </Link>
                            ,{' '}
                            <Link to="https://gdpr.eu/email-encryption/" target="_blank">
                                GDPR
                            </Link>
                            )
                        </p>
                    }
                >
                    <LemonSelect
                        options={[
                            { label: 'Marketing', value: 'marketing' },
                            { label: 'Transactional', value: 'transactional' },
                        ]}
                        placeholder="Select message type"
                    />
                </LemonField>

                <LemonField name="description" label="Description">
                    <LemonTextArea placeholder="Internal description for your team" rows={3} />
                </LemonField>

                <LemonField
                    name="public_description"
                    label="Public description"
                    help="This description will be shown to users in the email preferences page."
                >
                    <LemonTextArea
                        placeholder="e.g., Latest updates on feature launches, product improvements, and more."
                        rows={3}
                    />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
