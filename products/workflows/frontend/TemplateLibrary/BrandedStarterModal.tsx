import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useEffect, useRef } from 'react'

import { LemonBanner, LemonButton, LemonFileInput, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonColorGlyph } from 'lib/lemon-ui/LemonColor/LemonColorGlyph'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { urls } from 'scenes/urls'

import { brandedStarterLogic } from './brandedStarterLogic'
import type { brandedStarterLogicValues } from './brandedStarterLogic'
import type { MessageTemplateLogicProps } from './messageTemplateLogic'
import { messageTemplateSceneLogic } from './messageTemplateSceneLogic'
import { savedBrandLogic } from './savedBrandLogic'

export function BrandedStarterModal(props: MessageTemplateLogicProps): JSX.Element {
    const logic = brandedStarterLogic(props)
    useAttachedLogic(logic, messageTemplateSceneLogic(props))
    const {
        brand,
        brandChanged,
        brandValidationErrors,
        isBrandSubmitting,
        isEmailEditorReady,
        prefilledFrom,
        prefilledFromHost,
        detectedBrandLoading,
        savedBrandBlockReason,
        savedBrandLoadError,
        savedBrandLoading,
    } = useValues(logic)
    const { setBrandValue } = useActions(logic)
    const { loadSavedBrand } = useActions(savedBrandLogic)
    const busyReason = (isBrandSubmitting ? 'Generating your starter' : savedBrandBlockReason) ?? undefined
    const hostedLogoLabel = prefilledFrom === 'saved' ? 'Your saved logo' : 'Logo from your website'
    const chooseLogoRef = useRef<HTMLButtonElement>(null)
    const generateRef = useRef<HTMLButtonElement>(null)
    const nameRef = useRef<HTMLInputElement>(null)
    useEffect(() => {
        if (isBrandSubmitting) {
            generateRef.current?.focus()
        }
    }, [isBrandSubmitting])
    useEffect(() => {
        if (!savedBrandBlockReason) {
            nameRef.current?.focus()
        }
    }, [savedBrandBlockReason])
    const leaveStarter = (): void => router.actions.replace(urls.workflows('library'))
    const removeLogo = (): void => {
        setBrandValue('logo', null)
        chooseLogoRef.current?.focus()
    }
    return (
        <LemonModal
            title="Start with your brand"
            isOpen
            hasUnsavedInput={brandChanged}
            onClose={leaveStarter}
            footer={
                <>
                    <LemonButton data-attr="email-branded-starter-cancel" type="secondary" onClick={leaveStarter}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        ref={generateRef}
                        data-attr="email-branded-starter-generate"
                        type="primary"
                        htmlType="submit"
                        form="branded-starter"
                        loading={isBrandSubmitting}
                        disabledReason={
                            !isEmailEditorReady ? 'Loading email editor' : (savedBrandBlockReason ?? undefined)
                        }
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
                    Use your brand name and color as a starting point. You can edit the email before saving it as a
                    template.
                </p>
                {savedBrandLoadError && (
                    <LemonBanner
                        type="error"
                        action={
                            savedBrandLoadError.retryable
                                ? { children: 'Try again', onClick: loadSavedBrand, loading: savedBrandLoading }
                                : undefined
                        }
                        data-attr="email-branded-starter-saved-brand-unavailable"
                    >
                        {savedBrandLoadError.message}
                    </LemonBanner>
                )}
                <p
                    className="text-secondary empty:hidden"
                    aria-live="polite"
                    data-attr="email-branded-starter-prefilled"
                >
                    {prefillNotice({ prefilledFrom, prefilledFromHost, detectedBrandLoading, savedBrandBlockReason })}
                </p>
                <LemonField name="name" label="Brand name">
                    <LemonInput
                        value={brand.name}
                        onChange={(value) => setBrandValue('name', value)}
                        maxLength={255}
                        disabledReason={busyReason}
                        inputRef={nameRef}
                        autoFocus
                    />
                </LemonField>
                <LemonField name="primaryColor" label="Primary color">
                    <LemonInput
                        value={brand.primaryColor}
                        onChange={(value) => setBrandValue('primaryColor', value)}
                        prefix={
                            <LemonColorGlyph
                                color={brandValidationErrors.primaryColor ? null : brand.primaryColor}
                                size="small"
                            />
                        }
                        placeholder="#1d4aff"
                        maxLength={7}
                        disabledReason={busyReason}
                    />
                </LemonField>
                <LemonField name="logo" label="Logo (optional)" help="PNG, JPEG, GIF or WebP under 4 MB.">
                    <LemonFileInput
                        multiple={false}
                        accept="image/png,image/jpeg,image/gif,image/webp"
                        value={brand.logo instanceof File ? [brand.logo] : []}
                        onChange={(files) => setBrandValue('logo', files[0] ?? null)}
                        showUploadedFiles={false}
                        disabledReason={busyReason}
                        callToAction={
                            <LemonButton
                                ref={chooseLogoRef}
                                data-attr="email-branded-starter-logo-choose"
                                type="secondary"
                                disabledReason={busyReason}
                            >
                                Choose a logo
                            </LemonButton>
                        }
                    />
                </LemonField>
                {brand.logo && (
                    <div className="flex items-center gap-2 min-w-0">
                        {brand.logo instanceof File ? (
                            <span className="truncate" title={brand.logo.name}>
                                {brand.logo.name}
                            </span>
                        ) : (
                            <>
                                <img
                                    src={brand.logo}
                                    alt=""
                                    className="h-8 w-8 shrink-0 rounded border object-contain"
                                />
                                <span className="truncate">{hostedLogoLabel}</span>
                            </>
                        )}
                        <LemonButton
                            data-attr="email-branded-starter-logo-remove"
                            type="tertiary"
                            size="small"
                            disabledReason={busyReason}
                            onClick={removeLogo}
                        >
                            Remove logo
                        </LemonButton>
                    </div>
                )}
            </Form>
        </LemonModal>
    )
}

function prefillNotice({
    prefilledFrom,
    prefilledFromHost,
    detectedBrandLoading,
    savedBrandBlockReason,
}: Pick<
    brandedStarterLogicValues,
    'prefilledFrom' | 'prefilledFromHost' | 'detectedBrandLoading' | 'savedBrandBlockReason'
>): string | null {
    if (prefilledFrom === 'saved') {
        return 'This is your saved brand. Generating the starter saves any changes.'
    }
    if (prefilledFromHost) {
        return `We filled this in from ${prefilledFromHost}. You can change any field.`
    }
    return detectedBrandLoading && !savedBrandBlockReason ? 'Checking your website for your brand.' : null
}
