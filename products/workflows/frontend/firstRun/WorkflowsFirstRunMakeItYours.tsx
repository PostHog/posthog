import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { EmailTemplater } from 'scenes/hog-functions/email-templater/EmailTemplater'
import { urls } from 'scenes/urls'

import { firstRunGalleryLogic } from './firstRunGalleryLogic'
import { firstRunMakeItYoursLogic } from './firstRunMakeItYoursLogic'
import { MakeItYoursActions } from './MakeItYoursActions'
import { MakeItYoursEmailList } from './MakeItYoursEmailList'
import { TemplateStartsOnLine } from './TemplateStartsOnLine'

export function WorkflowsFirstRunMakeItYours({ templateId }: { templateId: string }): JSX.Element | null {
    const logic = firstRunMakeItYoursLogic({ templateId })
    const {
        firstRunEnabled,
        galleryTemplates,
        galleryLoadFailed,
        pickedTemplate,
        templateEmails,
        openEmail,
        openEmailPosition,
    } = useValues(logic)
    const { editEmail } = useActions(logic)
    const { loadEmailTemplates } = useActions(firstRunGalleryLogic)
    const backToGallery = (): void => router.actions.push(urls.workflows())

    if (!firstRunEnabled) {
        return null
    }

    if (galleryLoadFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadEmailTemplates }}>
                Couldn't load the template. Try again, or go back to the templates.
            </LemonBanner>
        )
    }
    if (galleryTemplates === null) {
        return <LemonSkeleton className="h-96" />
    }
    if (!pickedTemplate || !openEmail) {
        return (
            <LemonBanner type="warning" action={{ children: 'All templates', onClick: backToGallery }}>
                This template is not in the gallery anymore. Pick another one.
            </LemonBanner>
        )
    }

    const { template } = pickedTemplate
    const hasSeveralEmails = templateEmails.length > 1

    return (
        <div className="@container/first-run flex flex-col gap-4" data-attr="workflows-first-run-make-it-yours">
            <div className="flex flex-wrap items-start gap-3">
                <LemonButton size="small" icon={<IconArrowLeft />} onClick={backToGallery} data-attr="first-run-back">
                    All templates
                </LemonButton>
                <div className="flex min-w-0 flex-col gap-1">
                    <h2 className="mb-0 text-xl font-semibold">Make it yours: {template.name}</h2>
                    <div className="text-sm">
                        <TemplateStartsOnLine galleryTemplate={pickedTemplate} />
                    </div>
                </div>
            </div>
            {/* Below 56rem the side column no longer fits beside the editor: the email list moves above it and the actions below. */}
            <div className="grid gap-4 @min-[56rem]/first-run:grid-cols-[minmax(0,1fr)_20rem] @min-[56rem]/first-run:grid-rows-[auto_1fr]">
                {hasSeveralEmails && (
                    <div className="@min-[56rem]/first-run:col-start-2 @min-[56rem]/first-run:row-start-1">
                        <MakeItYoursEmailList templateId={templateId} />
                    </div>
                )}
                <div className="flex min-w-0 flex-col gap-2 @min-[56rem]/first-run:col-start-1 @min-[56rem]/first-run:row-start-1 @min-[56rem]/first-run:row-span-2">
                    {hasSeveralEmails && openEmailPosition && (
                        <span className="text-sm font-medium" data-attr="first-run-open-email">
                            Email {openEmailPosition.index} of {openEmailPosition.total}
                        </span>
                    )}
                    {/* The template type hides the From and To fields: the first-run sender is fixed, and the
                        recipient comes from the trigger. The editor remounts per email, so a canvas export can
                        never land on the email opened after it. */}
                    <div className="flex min-h-[40rem] flex-col overflow-hidden rounded border bg-surface-primary">
                        <EmailTemplater
                            key={openEmail.id}
                            type="native_email_template"
                            layout="inline"
                            templating="liquid"
                            value={openEmail.email}
                            onChange={(value) => editEmail(openEmail.id, value)}
                        />
                    </div>
                </div>
                <div className="@min-[56rem]/first-run:col-start-2 @min-[56rem]/first-run:row-start-2">
                    <MakeItYoursActions templateId={templateId} />
                </div>
            </div>
        </div>
    )
}
