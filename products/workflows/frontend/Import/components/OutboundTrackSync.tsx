import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { customerIOImportLogic } from '../customerIOImportLogic'

export function OutboundTrackSync(): JSX.Element {
    const {
        syncConfig,
        trackSiteId,
        trackApiKey,
        trackRegion,
        isSavingTrack,
        trackError,
        isRemovingTrackConfig,
        trackEnabled,
        hasTrackCredentials,
    } = useValues(customerIOImportLogic)
    const { setTrackSiteId, setTrackApiKey, setTrackRegion, saveTrackConfig, toggleTrackSync, removeTrackConfig } =
        useActions(customerIOImportLogic)

    return (
        <div className="space-y-4">
            <p className="text-sm text-muted">
                When users change their preferences on the PostHog-managed page, automatically sync those changes back
                to Customer.io. Only categories imported from Customer.io are synced.
            </p>

            {trackError && (
                <LemonBanner type="error" className="text-sm">
                    {trackError}
                </LemonBanner>
            )}

            {trackEnabled && <LemonBanner type="success">Outbound sync is active.</LemonBanner>}

            {hasTrackCredentials ? (
                <>
                    <div className="space-y-2">
                        <label className="LemonLabel">Track API credentials</label>
                        <LemonInput
                            value="••••••••••••••••"
                            disabledReason="Can't be changed"
                            suffix={
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    status="danger"
                                    tooltip="Remove track integration"
                                    onClick={removeTrackConfig}
                                    data-attr="customerio-track-sync-remove"
                                    loading={isRemovingTrackConfig}
                                    icon={<IconTrash className="text-danger" />}
                                />
                            }
                        />
                    </div>
                    <div className="flex justify-end">
                        {syncConfig?.track_enabled ? (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                onClick={() => toggleTrackSync(false)}
                                data-attr="customerio-track-sync-disable"
                                loading={isSavingTrack}
                            >
                                Disable sync
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="primary"
                                onClick={() => toggleTrackSync(true)}
                                data-attr="customerio-track-sync-enable"
                                loading={isSavingTrack}
                            >
                                Enable sync
                            </LemonButton>
                        )}
                    </div>
                </>
            ) : (
                <div className="space-y-3">
                    <div className="space-y-2">
                        <label className="LemonLabel">Region</label>
                        <LemonSegmentedButton
                            value={trackRegion}
                            onChange={setTrackRegion}
                            options={[
                                { value: 'US', label: 'US', tooltip: 'track.customer.io' },
                                { value: 'EU', label: 'EU', tooltip: 'track-eu.customer.io' },
                            ]}
                            size="small"
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="LemonLabel">Site ID</label>
                        <LemonInput
                            value={trackSiteId}
                            onChange={setTrackSiteId}
                            placeholder="Your Customer.io site ID"
                            autoComplete="off"
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="LemonLabel">Track API key</label>
                        <LemonInput
                            value={trackApiKey}
                            onChange={setTrackApiKey}
                            placeholder="Your Customer.io Track API key"
                            type="password"
                            autoComplete="off"
                        />
                    </div>
                    <p className="text-xs text-muted-alt">
                        Find these in Customer.io under Settings → API and webhook credentials → Track API Keys.
                    </p>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            onClick={saveTrackConfig}
                            data-attr="customerio-track-sync-save"
                            loading={isSavingTrack}
                            disabledReason={!trackSiteId || !trackApiKey ? 'Enter site ID and API key' : undefined}
                        >
                            Enable sync
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
