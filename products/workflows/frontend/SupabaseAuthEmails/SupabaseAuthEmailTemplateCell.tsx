import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { SupabaseEmailTypeApi } from 'products/messaging/frontend/generated/api.schemas'

import { supabaseAuthEmailsLogic } from './supabaseAuthEmailsLogic'

/** Picks the template for one Supabase email type and shows how many emails it sent. */
export function SupabaseAuthEmailTemplateCell({ emailType }: { emailType: SupabaseEmailTypeApi }): JSX.Element {
    const { settings, settingsLoading, transactionalTemplates, templatesLoadFailed, sendCounts } =
        useValues(supabaseAuthEmailsLogic)
    const { setTemplate } = useActions(supabaseAuthEmailsLogic)

    const templateId = settings?.templates[emailType.value]
    const sendCount = templateId ? sendCounts[templateId] : undefined
    const templateOptions = [
        { value: null, label: 'No template' },
        ...(transactionalTemplates ?? []).map((template) => ({ value: template.id, label: template.name })),
    ]

    return (
        <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-1">
                <div className="min-w-0 flex-1">
                    <LemonSelect
                        size="small"
                        fullWidth
                        value={templateId ?? null}
                        options={templateOptions}
                        onChange={(newTemplateId) => setTemplate(emailType.value, newTemplateId)}
                        disabledReason={
                            templatesLoadFailed
                                ? "Couldn't load templates"
                                : transactionalTemplates === null
                                  ? 'Loading templates'
                                  : settingsLoading
                                    ? 'Saving'
                                    : undefined
                        }
                        data-attr="workflows-supabase-auth-emails-template"
                    />
                </div>
                {templateId && (
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        to={urls.workflowsLibraryTemplate(templateId)}
                        targetBlank
                        hideExternalLinkIcon
                        tooltip="Edit template"
                        data-attr="workflows-supabase-auth-emails-edit-template"
                    />
                )}
            </div>
            {sendCount !== undefined && (
                <span className="text-secondary text-xs">{`Sent ${humanFriendlyNumber(sendCount)} in the last 30 days`}</span>
            )}
        </div>
    )
}
