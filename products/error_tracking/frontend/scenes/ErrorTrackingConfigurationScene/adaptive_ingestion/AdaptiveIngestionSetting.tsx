import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { LemonBanner, LemonSwitch } from '@posthog/lemon-ui'
import { Field, FieldLabel, Item, ItemContent, ItemDescription, Skeleton, Switch } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { teamLogic } from 'scenes/teamLogic'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { adaptiveIngestionLogic } from './adaptiveIngestionLogic'

export function AdaptiveIngestionSetting(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = adaptiveIngestionLogic({ projectId: currentTeamId ? String(currentTeamId) : '' })
    const { settings, settingsLoading, settingsError } = useValues(logic)
    const { setAdaptiveIngestionEnabled } = useActions(logic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const switchId = useId()

    if (!currentTeamId || (!settings && !settingsError)) {
        return todayRailNav ? <Skeleton className="w-full h-8" /> : <LemonSkeleton className="w-full h-10" />
    }

    if (settingsError) {
        return todayRailNav ? (
            <Item tone="destructive" size="sm">
                <ItemContent>
                    <ItemDescription>Couldn't load this setting. Refresh the page to try again.</ItemDescription>
                </ItemContent>
            </Item>
        ) : (
            <LemonBanner type="error">Couldn't load this setting. Refresh the page to try again.</LemonBanner>
        )
    }

    if (todayRailNav) {
        return (
            <Field orientation="horizontal" className="w-fit">
                <Switch
                    id={switchId}
                    checked={Boolean(settings?.adaptive_ingestion_enabled)}
                    onCheckedChange={setAdaptiveIngestionEnabled}
                    disabled={settingsLoading}
                    disabledReason={errorTrackingEditAccessDisabledReason()}
                    data-attr="adaptive-ingestion-toggle"
                />
                <FieldLabel htmlFor={switchId}>Adaptive ingestion</FieldLabel>
            </Field>
        )
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
