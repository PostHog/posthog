import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { SupabaseAuthEmailsStatus, supabaseAuthEmailsLogic } from './supabaseAuthEmailsLogic'

const STATUS_TAGS: Record<SupabaseAuthEmailsStatus, { label: string; type: LemonTagType }> = {
    connected: { label: 'Connected', type: 'success' },
    incomplete: { label: 'Incomplete', type: 'warning' },
    'not-set-up': { label: 'Not set up', type: 'muted' },
}

/** The Supabase entry in the auth email catalog. Same shape as a channel catalog card. */
export function SupabaseAuthEmailsCard({ status }: { status: SupabaseAuthEmailsStatus }): JSX.Element {
    const { settings } = useValues(supabaseAuthEmailsLogic)
    const { openSetup } = useActions(supabaseAuthEmailsLogic)
    const tag = STATUS_TAGS[status]
    const mappedCount = Object.keys(settings?.templates ?? {}).length

    return (
        <LemonCard
            hoverEffect={false}
            className="flex items-start gap-3 p-3"
            data-attr="workflows-supabase-auth-emails"
        >
            <img src="/static/services/supabase.svg" alt="" className="size-5 shrink-0 mt-0.5" />
            <div className="flex flex-col gap-1 flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">Supabase</span>
                    <LemonTag size="small" type={tag.type}>
                        {tag.label}
                    </LemonTag>
                </div>
                <span className="text-secondary text-sm">
                    Send your Supabase project's sign-up, magic link and password reset emails from PostHog.
                </span>
                {status !== 'not-set-up' && (
                    <span className="text-secondary text-xs">
                        {mappedCount === 1 ? '1 email mapped' : `${mappedCount} emails mapped`}
                    </span>
                )}
            </div>
            <LemonButton
                size="small"
                type={status === 'not-set-up' ? 'primary' : 'secondary'}
                className="shrink-0"
                onClick={openSetup}
                data-attr="workflows-supabase-auth-emails-open-setup"
            >
                {status === 'not-set-up' ? 'Connect' : 'Manage'}
            </LemonButton>
        </LemonCard>
    )
}
