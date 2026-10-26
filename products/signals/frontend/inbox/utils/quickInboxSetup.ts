import type { ReplayScannerApi } from '../../../../replay_vision/frontend/generated/api.schemas'
import type { InboxOnboardingDraftApi, SignalScoutConfigApi } from '../../generated/api.schemas'
import { InboxSetupSource, newInboxSetupDraft } from './inboxSetup'

export function quickInboxSetupDraft(
    sources: InboxSetupSource[],
    scanners: ReplayScannerApi[],
    configs: SignalScoutConfigApi[]
): InboxOnboardingDraftApi | null {
    const general = configs.find(
        (config) =>
            config.skill_name === 'signals-scout-general' &&
            config.scout_origin === 'canonical' &&
            !config.deprecation &&
            !config.lifecycle_locked
    )
    if (!general) {
        return null
    }
    return {
        ...newInboxSetupDraft(
            sources,
            scanners.filter((scanner) => scanner.enabled).map((scanner) => scanner.id)
        ),
        step: 'github',
        suggestions: [
            {
                id: `builtin:${general.id}`,
                kind: 'canonical',
                skill_name: general.skill_name,
                title: 'General scout',
                why_here: 'Explore available data and investigate what needs your attention.',
                description: '',
                draft_body: '',
                proposed_config: {
                    run_interval_minutes: general.run_interval_minutes ?? 1440,
                    run_cron_schedule: general.run_cron_schedule,
                    emit: true,
                },
                gap: true,
                confidence: 'medium',
            },
        ],
    }
}
