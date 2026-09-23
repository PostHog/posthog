import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { heatmapLogic } from '../scenes/heatmap/heatmapLogic'
import { HeatmapPageFields } from './HeatmapPageFields'
import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'
import { HeatmapScreenshotAccessNotice } from './HeatmapScreenshotAccessNotice'
import { HeatmapsForbiddenURL } from './HeatmapsForbiddenURL'

export function HeatmapHeader(): JSX.Element {
    const {
        pageUrlDraft,
        isPageUrlDraftValid,
        pageUrlDraftIsPattern,
        generatingScreenshot,
        source,
        urlEditDisabledReason,
        regenerateDisabledReason,
        reloadPreviewDisabledReason,
        previewType,
        saving,
        type,
        renderSettingsEditDisabledReason,
        saveDisabledReason,
        hasUnsavedChanges,
        pageSettingsOpen,
        screenshotError,
        displayUrl,
    } = useValues(heatmapLogic)
    const { dataUrl, isBrowserUrlAuthorized } = useValues(heatmapsBrowserLogic)
    const {
        setPageUrlDraft,
        regenerateScreenshot,
        reloadPreview,
        setType,
        updateHeatmap,
        openPageSettings,
        closePageSettings,
    } = useActions(heatmapLogic)

    const refreshPreview =
        previewType === 'screenshot'
            ? {
                  label: 'Regenerate screenshot',
                  onClick: regenerateScreenshot,
                  disabledReason: regenerateDisabledReason,
              }
            : { label: 'Reload page', onClick: reloadPreview, disabledReason: reloadPreviewDisabledReason }

    return (
        <div>
            <div className="flex flex-wrap gap-2 items-center">
                <LemonLabel htmlFor="heatmap-page-url">Page URL</LemonLabel>
                <LemonInput
                    id="heatmap-page-url"
                    className="flex-1 min-w-48"
                    size="small"
                    placeholder="https://www.example.com/pricing"
                    value={pageUrlDraft}
                    onChange={setPageUrlDraft}
                    onPressEnter={updateHeatmap}
                    disabledReason={urlEditDisabledReason}
                    status={pageUrlDraft && !isPageUrlDraftValid ? 'danger' : undefined}
                    data-attr="heatmap-page-url"
                />
                <LemonButton type="secondary" size="small" onClick={openPageSettings} data-attr="heatmap-page-settings">
                    Page settings
                </LemonButton>
                {source === 'toolbar' && <LemonTag>Captured from toolbar</LemonTag>}
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    aria-label={refreshPreview.label}
                    tooltip={refreshPreview.label}
                    onClick={refreshPreview.onClick}
                    loading={generatingScreenshot}
                    disabledReason={refreshPreview.disabledReason}
                    data-attr="heatmap-refresh-preview"
                />
            </div>
            {pageUrlDraft && !isPageUrlDraftValid && (
                <p className="text-xs text-danger mt-1 mb-0">
                    {pageUrlDraftIsPattern
                        ? 'Enter a page URL without wildcards. Use the heatmap data URL in Page settings to match multiple pages.'
                        : 'Enter a valid URL, including https:// or http://.'}
                </p>
            )}
            <LemonModal
                isOpen={pageSettingsOpen}
                onClose={closePageSettings}
                closable={!saving}
                title="Page settings"
                width={560}
                footer={
                    <>
                        <LemonButton
                            type="secondary"
                            onClick={closePageSettings}
                            disabledReason={saving ? 'Saving changes' : null}
                        >
                            Close
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={updateHeatmap}
                            loading={saving}
                            disabledReason={saveDisabledReason || (!hasUnsavedChanges ? 'No changes to save' : null)}
                            data-attr="heatmap-page-settings-save"
                        >
                            Save heatmap
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-6" data-attr="heatmap-page-settings-content">
                    <div>
                        <LemonLabel>Page background</LemonLabel>
                        <LemonSegmentedButton
                            value={type}
                            onChange={setType}
                            disabledReason={renderSettingsEditDisabledReason ?? undefined}
                            options={[
                                { value: 'screenshot', label: 'Screenshot' },
                                { value: 'iframe', label: 'Live page' },
                            ]}
                            size="small"
                        />
                        <p className="text-xs text-muted mt-2 mb-0">
                            A screenshot captures the full page. A live page loads the website directly.
                        </p>
                    </div>
                    {type === 'screenshot' && source !== 'toolbar' && !screenshotError && (
                        <HeatmapScreenshotAccessNotice url={displayUrl} />
                    )}
                    <HeatmapPageFields
                        dataUrlPlaceholderFallback="Enter a URL"
                        dataUrlHelp="Defaults to the page URL. Add * to match multiple pages."
                        consentHelp="Close cookie and consent banners before taking the screenshot."
                        showConsent={type === 'screenshot'}
                    />
                </div>
            </LemonModal>
            {dataUrl && !isBrowserUrlAuthorized ? <HeatmapsForbiddenURL /> : null}
        </div>
    )
}
