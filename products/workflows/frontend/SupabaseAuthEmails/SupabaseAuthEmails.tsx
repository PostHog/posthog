import { useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { CATALOG_GRID_CLASS } from '../Channels/channelSummary'
import { SupabaseAuthEmailsCard } from './SupabaseAuthEmailsCard'
import { supabaseAuthEmailsLogic } from './supabaseAuthEmailsLogic'
import { SupabaseAuthEmailsModal } from './SupabaseAuthEmailsModal'

/** Auth email providers that send through transactional templates. Supabase is the only one so far. */
export function SupabaseAuthEmails(): JSX.Element {
    const { status, settingsLoadFailed } = useValues(supabaseAuthEmailsLogic)

    return (
        <section className="flex flex-col gap-2" data-attr="workflows-auth-email-catalog">
            <h3 className="mb-0 text-base font-semibold">Auth emails</h3>
            <div className={CATALOG_GRID_CLASS}>
                {status ? (
                    <SupabaseAuthEmailsCard status={status} />
                ) : settingsLoadFailed ? (
                    <LemonBanner type="error">
                        Couldn't load the Supabase settings. Refresh the page to try again.
                    </LemonBanner>
                ) : (
                    <LemonSkeleton className="h-20" />
                )}
            </div>
            <SupabaseAuthEmailsModal />
        </section>
    )
}
