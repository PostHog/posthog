import type { ReplayScannerApi } from '../../../../replay_vision/frontend/generated/api.schemas'
import type { InboxOnboardingDraftApi, ScoutSuggestionItemApi, SignalScoutConfigApi } from '../../generated/api.schemas'
import { InboxSetupSource, newInboxSetupDraft } from './inboxSetup'
import { inboxSetupScoutCopy } from './inboxSetupScouts'

const GENERAL_SCOUT = 'signals-scout-general'

function quickSetupSuggestion(config: SignalScoutConfigApi): ScoutSuggestionItemApi {
    const copy = inboxSetupScoutCopy(config.skill_name)
    return {
        id: `builtin:${config.id}`,
        kind: 'canonical',
        skill_name: config.skill_name,
        title: copy?.title ?? (config.display_name || config.skill_name),
        why_here: copy?.description ?? 'Watch this project on a schedule and report what needs your attention.',
        description: '',
        draft_body: '',
        proposed_config: {
            run_interval_minutes: config.run_interval_minutes ?? 1440,
            run_cron_schedule: config.run_cron_schedule,
            emit: true,
        },
        gap: true,
        confidence: 'medium',
    }
}

export function quickInboxSetupDraft(
    sources: InboxSetupSource[],
    scanners: ReplayScannerApi[],
    configs: SignalScoutConfigApi[],
    skillNames: string[] = [GENERAL_SCOUT]
): InboxOnboardingDraftApi | null {
    const usableConfig = (skillName: string): SignalScoutConfigApi | undefined =>
        configs.find(
            (config) =>
                config.skill_name === skillName &&
                config.scout_origin === 'canonical' &&
                !config.deprecation &&
                !config.lifecycle_locked
        )
    const general = usableConfig(GENERAL_SCOUT)
    if (!general) {
        return null
    }
    const scouts = [
        general,
        ...skillNames.flatMap((skillName) => {
            const config = skillName === GENERAL_SCOUT ? undefined : usableConfig(skillName)
            return config ? [config] : []
        }),
    ]
    return {
        ...newInboxSetupDraft(
            sources,
            scanners.filter((scanner) => scanner.enabled).map((scanner) => scanner.id)
        ),
        step: 'github',
        setup_mode: 'quick',
        suggestions: scouts.map(quickSetupSuggestion),
    }
}
