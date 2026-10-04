import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'

import { LemonButton, LemonFileInput, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { brandedStarterLogic } from './brandedStarterLogic'
import type { MessageTemplateLogicProps } from './messageTemplateLogic'

export function BrandedStarterModal(props: MessageTemplateLogicProps): JSX.Element {
    const logic = brandedStarterLogic(props)
    const { brand, isBrandSubmitting, isEmailEditorReady } = useValues(logic)
    const { setBrandValue } = useActions(logic)
    const busyReason = isBrandSubmitting ? 'Generating your starter' : undefined
    return (
        <LemonModal
            title="Start with your brand"
            isOpen
            onClose={isBrandSubmitting ? undefined : () => router.actions.replace(urls.workflows('library'))}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        disabledReason={busyReason}
                        onClick={() => router.actions.replace(urls.workflows('library'))}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        form="branded-starter"
                        loading={isBrandSubmitting}
                        disabledReason={!isEmailEditorReady ? 'Loading email editor' : undefined}
                    >
                        Generate starter
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={brandedStarterLogic}
                props={props}
                formKey="brand"
                id="branded-starter"
                enableFormOnSubmit
                className="space-y-4 w-full max-w-120"
            >
                <p>
                    Use your name and color as a starting point. You can edit the email before saving it as a template.
                </p>
                <Field name="name" label="Brand name">
                    <LemonInput
                        value={brand.name}
                        onChange={(value) => setBrandValue('name', value)}
                        maxLength={255}
                        disabledReason={busyReason}
                        autoFocus
                    />
                </Field>
                <Field name="primaryColor" label="Primary color">
                    <LemonInput
                        value={brand.primaryColor}
                        onChange={(value) => setBrandValue('primaryColor', value)}
                        placeholder="#1d4aff"
                        maxLength={7}
                        disabledReason={busyReason}
                    />
                </Field>
                <Field name="logo" label="Logo (optional)">
                    <LemonFileInput
                        multiple={false}
                        accept="image/png,image/jpeg,image/gif,image/webp"
                        value={brand.logo ? [brand.logo] : []}
                        onChange={(files) => setBrandValue('logo', files[0] ?? null)}
                        disabledReason={busyReason}
                        callToAction="Choose a logo"
                    />
                </Field>
                <p className="text-secondary text-sm mb-0">PNG, JPEG, GIF or WebP under 4 MB.</p>
            </Form>
        </LemonModal>
    )
}
