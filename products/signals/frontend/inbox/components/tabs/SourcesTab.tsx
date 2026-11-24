import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { signalSourcesLogic } from '../../signalSourcesLogic'
import { AgentsRoster } from '../config/AgentsRoster'
import { SlackChannelScoutsCard } from '../config/SlackChannelScoutsCard'
import { SourceCatalog } from '../config/SourceCatalog'
import { SettingsSection } from './SettingsSection'

export function SourcesTab(): JSX.Element {
    const { loadSources, loadSourceConfigs, loadVisionScanners, loadProductDataEvents } = useActions(signalSourcesLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    useEffect(() => {
        loadSources()
        loadSourceConfigs()
        loadVisionScanners()
        loadProductDataEvents()
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-6">
            <SettingsSection
                title="Your sources"
                description="Each source watches for signals, and spins up an agent to look into them."
            >
                <AgentsRoster />
            </SettingsSection>
            {featureFlags[FEATURE_FLAGS.INBOX_SLACK_CHANNEL_SCOUTS] && (
                <SettingsSection
                    title="Slack channel scouts"
                    description="Scouts that read your Slack channels for problems and requests."
                >
                    <SlackChannelScoutsCard />
                </SettingsSection>
            )}
            <SettingsSection
                title="Available sources"
                description="Connect a tool so self-driving can investigate its signals alongside your PostHog data."
            >
                <SourceCatalog />
            </SettingsSection>
        </div>
    )
}
