import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonTable,
} from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { SupabaseEmailTypeApi } from 'products/messaging/frontend/generated/api.schemas'

import { supabaseAuthEmailsLogic } from './supabaseAuthEmailsLogic'

/** Connects a Supabase project's Send Email Hook and maps each auth email to a transactional template. */
export function SupabaseAuthEmailsModal(): JSX.Element | null {
    const {
        isSetupOpen,
        settings,
        settingsLoading,
        status,
        supabaseUrl,
        hookSecret,
        connectionChanged,
        transactionalTemplates,
        templatesLoadFailed,
        missingStarterTypes,
    } = useValues(supabaseAuthEmailsLogic)
    const {
        closeSetup,
        setSupabaseUrl,
        setHookSecret,
        saveConnection,
        setTemplate,
        createStarterTemplates,
        loadTemplates,
        disconnect,
    } = useActions(supabaseAuthEmailsLogic)

    if (!settings) {
        return null
    }

    const templateOptions = [
        { value: null, label: 'No template' },
        ...(transactionalTemplates ?? []).map((template) => ({ value: template.id, label: template.name })),
    ]

    return (
        <LemonModal
            isOpen={isSetupOpen}
            onClose={closeSetup}
            hasUnsavedInput={connectionChanged}
            title="Supabase auth emails"
            description="Send your Supabase project's sign-up, magic link and password reset emails from PostHog. Each email is recorded against the Supabase user's ID."
            width={720}
            footer={
                <>
                    {status !== 'not-set-up' && (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            disabledReason={settingsLoading ? 'Saving' : undefined}
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Disconnect your Supabase project?',
                                    description:
                                        "PostHog removes the project URL, hook secret and template choices, and stops sending. Turn off the Send Email hook in Supabase first, or your users' auth emails will fail. Your templates stay.",
                                    primaryButton: {
                                        children: 'Disconnect',
                                        status: 'danger',
                                        onClick: disconnect,
                                        'data-attr': 'workflows-supabase-auth-emails-disconnect-confirm',
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                            data-attr="workflows-supabase-auth-emails-disconnect"
                        >
                            Disconnect
                        </LemonButton>
                    )}
                    <div className="flex-1" />
                    <LemonButton
                        type="secondary"
                        onClick={closeSetup}
                        disabledReason={connectionChanged ? 'Save the connection first' : undefined}
                        data-attr="workflows-supabase-auth-emails-done"
                    >
                        Done
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-6">
                <div className="flex flex-col gap-3">
                    <h4 className="mb-0 font-semibold">1. Connect your Supabase project</h4>
                    <LemonField.Pure
                        label="Hook URL"
                        help="In Supabase, open Authentication, then Hooks. Add a Send Email hook, choose HTTPS and paste this URL."
                    >
                        <LemonInput
                            value={settings.hook_url}
                            className="font-mono"
                            suffix={
                                <CopyToClipboardInline
                                    explicitValue={settings.hook_url}
                                    description="hook URL"
                                    data-attr="workflows-supabase-auth-emails-copy-hook-url"
                                />
                            }
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Supabase project URL">
                        <LemonInput
                            value={supabaseUrl}
                            onChange={setSupabaseUrl}
                            placeholder="https://abcdefgh.supabase.co"
                            data-attr="workflows-supabase-auth-emails-url"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Hook secret"
                        help="Generate a secret on the same Supabase screen and paste it here. It starts with v1,whsec_."
                    >
                        <LemonInput
                            type="password"
                            value={hookSecret}
                            onChange={setHookSecret}
                            placeholder={
                                settings.has_hook_secret ? 'Saved. Paste a new secret to replace it.' : 'v1,whsec_…'
                            }
                            data-attr="workflows-supabase-auth-emails-secret"
                        />
                    </LemonField.Pure>
                    <div>
                        <LemonButton
                            type="primary"
                            onClick={saveConnection}
                            loading={settingsLoading}
                            disabledReason={!connectionChanged ? 'Nothing to save' : undefined}
                            data-attr="workflows-supabase-auth-emails-save-connection"
                        >
                            Save connection
                        </LemonButton>
                    </div>
                </div>
                <div className="flex flex-col gap-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-60 flex-1">
                            <h4 className="mb-0 font-semibold">2. Pick a template for each email</h4>
                            <p className="mb-0 text-secondary text-sm">
                                Only transactional templates marked sensitive can send these, so sign-in codes and reset
                                links stay out of stored emails. A template can use{' '}
                                <code>{'{{ variables.confirmation_url }}'}</code> and{' '}
                                <code>{'{{ variables.token }}'}</code>. An email with no template fails in Supabase.
                            </p>
                            {Object.keys(settings.templates).length > 0 && (
                                <Link
                                    to={urls.workflows('library')}
                                    target="_blank"
                                    className="text-sm"
                                    data-attr="workflows-supabase-auth-emails-view-templates"
                                >
                                    View templates
                                </Link>
                            )}
                        </div>
                        <LemonButton
                            type="secondary"
                            onClick={createStarterTemplates}
                            loading={settingsLoading}
                            disabledReason={
                                missingStarterTypes?.length === 0 ? 'Every email already has a template' : undefined
                            }
                            data-attr="workflows-supabase-auth-emails-starter-templates"
                        >
                            {missingStarterTypes?.length === 1
                                ? 'Create 1 starter template'
                                : missingStarterTypes?.length
                                  ? `Create ${missingStarterTypes.length} starter templates`
                                  : 'Create starter templates'}
                        </LemonButton>
                    </div>
                    {templatesLoadFailed && (
                        <LemonBanner
                            type="error"
                            action={{
                                children: 'Try again',
                                onClick: loadTemplates,
                                'data-attr': 'workflows-supabase-auth-emails-retry-templates',
                            }}
                        >
                            Couldn't load your templates.
                        </LemonBanner>
                    )}
                    <LemonTable<SupabaseEmailTypeApi>
                        dataSource={settings.email_types}
                        rowKey="value"
                        size="small"
                        columns={[
                            {
                                title: 'Email',
                                key: 'label',
                                render: (_, emailType) => emailType.label,
                            },
                            {
                                title: 'Template',
                                key: 'template',
                                width: '50%',
                                render: (_, emailType) => (
                                    <div className="flex items-center gap-1">
                                        <div className="min-w-0 flex-1">
                                            <LemonSelect
                                                size="small"
                                                fullWidth
                                                value={settings.templates[emailType.value] ?? null}
                                                options={templateOptions}
                                                onChange={(templateId) => setTemplate(emailType.value, templateId)}
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
                                        {settings.templates[emailType.value] && (
                                            <LemonButton
                                                size="small"
                                                icon={<IconPencil />}
                                                to={urls.workflowsLibraryTemplate(settings.templates[emailType.value])}
                                                targetBlank
                                                hideExternalLinkIcon
                                                tooltip="Edit template"
                                                data-attr="workflows-supabase-auth-emails-edit-template"
                                            />
                                        )}
                                    </div>
                                ),
                            },
                        ]}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <h4 className="mb-0 font-semibold">3. Turn on the hook in Supabase</h4>
                    <p className="mb-0 text-secondary text-sm">
                        Once each email has a template, turn on the Send Email hook in Supabase. To go back to
                        Supabase's own emails, turn the hook off there.
                    </p>
                </div>
            </div>
        </LemonModal>
    )
}
