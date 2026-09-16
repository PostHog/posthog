import { useActions, useValues } from 'kea'

import { LemonInput, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { heatmapLogic } from '../scenes/heatmap/heatmapLogic'

export interface HeatmapPageFieldsProps {
    dataUrlPlaceholderFallback: string
    dataUrlHelp: React.ReactNode
    consentHelp: React.ReactNode
    showDataUrl?: boolean
    showConsent?: boolean
}

export function HeatmapPageFields({
    dataUrlPlaceholderFallback,
    dataUrlHelp,
    consentHelp,
    showDataUrl = true,
    showConsent = true,
}: HeatmapPageFieldsProps): JSX.Element {
    const {
        dataUrl,
        displayUrl,
        type,
        blockConsentModals,
        urlEditDisabledReason,
        renderSettingsEditDisabledReason,
        isBrowserUrlValid,
    } = useValues(heatmapLogic)
    const { setDataUrl, setDataUrlUserTouched, setBlockConsentModals } = useActions(heatmapLogic)

    return (
        <div className="flex flex-col gap-4">
            {showDataUrl ? (
                <div>
                    <LemonLabel>Heatmap data URL</LemonLabel>
                    <LemonInput
                        size="small"
                        placeholder={displayUrl ? `Same as page URL: ${displayUrl}` : dataUrlPlaceholderFallback}
                        value={dataUrl ?? ''}
                        onChange={(value) => {
                            setDataUrlUserTouched(true)
                            setDataUrl(value || null)
                        }}
                        fullWidth={true}
                        disabledReason={urlEditDisabledReason}
                        status={!isBrowserUrlValid ? 'danger' : undefined}
                    />
                    <div className="text-xs text-muted mt-1">{dataUrlHelp}</div>
                    {!isBrowserUrlValid && (
                        <div className="text-xs text-danger mt-1">
                            Enter a valid heatmap data URL. Wildcards are allowed.
                        </div>
                    )}
                </div>
            ) : null}
            {showConsent ? (
                <div>
                    <LemonSwitch
                        checked={blockConsentModals}
                        onChange={setBlockConsentModals}
                        label="Dismiss cookie & consent banners"
                        bordered
                        disabledReason={
                            renderSettingsEditDisabledReason ||
                            (type !== 'screenshot' ? 'Only available for screenshot heatmaps' : undefined)
                        }
                    />
                    <div className="text-xs text-muted mt-1">{consentHelp}</div>
                </div>
            ) : null}
        </div>
    )
}
