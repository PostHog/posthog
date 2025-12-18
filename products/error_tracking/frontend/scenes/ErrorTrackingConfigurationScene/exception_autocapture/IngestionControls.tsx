import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import IngestionControls from 'lib/components/IngestionControls'
import { IngestionControlsSummary } from 'lib/components/IngestionControls/Summary'
import { sdkPolicyConfigLogic } from 'lib/components/IngestionControls/sdkPolicyConfigLogic'

import { AccessControlResourceType } from '~/types'

export function ErrorTrackingIngestionControls({ disabled }: { disabled: boolean }): JSX.Element | null {
    const { config } = useValues(sdkPolicyConfigLogic)
    const { loadConfig } = useActions(sdkPolicyConfigLogic)

    useEffect(() => {
        loadConfig()
        // oxlint-disable-next-line exhaustive-deps
    }, [])

    if (!config) {
        return null
    }

    return (
        <IngestionControls
            logicKey="error-tracking"
            resourceType={AccessControlResourceType.ErrorTracking}
            matchType={config.match_type}
            onChangeMatchType={(value) => null}
        >
            {disabled && (
                <LemonBanner type="warning">
                    <strong>Exception autocapture is disabled.</strong> None of these triggers apply unless it is
                    enabled.
                </LemonBanner>
            )}
            <div className="flex flex-col gap-y-2">
                <IngestionControlsSummary triggers={config.triggers} />
                <div className="flex flex-col gap-y-2 border rounded py-2 px-4 mb-2">
                    <IngestionControls.MatchTypeSelect />
                    {/* <EventTriggerOptions />
                    <LinkedFlagSelector />
                    <Sampling /> */}
                </div>
            </div>
        </IngestionControls>
    )
}
