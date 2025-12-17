import { LemonBanner } from '@posthog/lemon-ui'

import IngestionControls from 'lib/components/IngestionControls'
import { IngestionControlsSummary } from 'lib/components/IngestionControls/Summary'

import { AccessControlResourceType } from '~/types'

export function ErrorTrackingIngestionControls({ disabled }: { disabled: boolean }): JSX.Element {
    return (
        <IngestionControls
            logicKey="error-tracking"
            resourceType={AccessControlResourceType.ErrorTracking}
            matchType="all"
            onChangeMatchType={(value) => null}
        >
            {disabled && (
                <LemonBanner type="warning">
                    <strong>Exception autocapture is disabled.</strong> None of these triggers apply unless it is
                    enabled.
                </LemonBanner>
            )}
            <div className="flex flex-col gap-y-2">
                <IngestionControlsSummary triggers={triggers} />
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
