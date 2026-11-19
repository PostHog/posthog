import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSwitch } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { teamLogic } from 'scenes/teamLogic'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { adaptiveIngestionLogic } from './adaptiveIngestionLogic'

export function AdaptiveIngestionSetting(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = adaptiveIngestionLogic({ projectId: currentTeamId ? String(currentTeamId) : '' })
    const { settings, settingsLoading, settingsError } = useValues(logic)
    const { setAdaptiveIngestionEnabled } = useActions(logic)

    if (!currentTeamId || (!settings && !settingsError)) {
        return <LemonSkeleton className="w-full h-10" />
    }

    if (settingsError) {
        return <LemonBanner type="error">Couldn't load this setting. Refresh the page to try again.</LemonBanner>
    }

    return (
        <LemonSwitch
            checked={Boolean(settings?.adaptive_ingestion_enabled)}
            onChange={setAdaptiveIngestionEnabled}
            loading={settingsLoading}
            disabledReason={errorTrackingEditAccessDisabledReason()}
            label="Adaptive ingestion"
            aria-label="Adaptive ingestion"
            bordered
            data-attr="adaptive-ingestion-toggle"
        />
    )
}
