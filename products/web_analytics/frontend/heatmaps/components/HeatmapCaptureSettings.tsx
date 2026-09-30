import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonInputSelect,
    LemonLabel,
    LemonSegmentedButton,
    LemonSkeleton,
} from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { heatmapCaptureSettingsLogic } from './heatmapCaptureSettingsLogic'

export function HeatmapCaptureSettings(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = heatmapCaptureSettingsLogic({ teamId: currentTeamId ?? 0 })
    const {
        settings,
        settingsLoading,
        captureMode,
        urlAllowlist,
        hasChanges,
        loadError,
        saveError,
        canCaptureAllUrls,
        captureUrlLimit,
        disabledPages,
        pagesLoading,
        pagesError,
    } = useValues(logic)
    const { loadSettings, loadPages, setCaptureMode, setUrlAllowlist, saveSettings } = useActions(logic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (loadError) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadSettings }}>
                Could not load heatmap capture settings. Try again.
            </LemonBanner>
        )
    }
    if (!settings) {
        return <LemonSkeleton />
    }

    const isAllowlist = captureMode === 'url_allowlist'
    const emptyAllowlist = isAllowlist && urlAllowlist.length === 0

    return (
        <div className="flex flex-col gap-3 max-w-160">
            <p className="mb-0">
                Choose which pages send heatmap data. Capture from every page, or only from the URLs you list. Data from
                pages that are not covered is not collected.
            </p>

            {!canCaptureAllUrls && (
                <LemonBanner type="warning" action={{ children: 'Upgrade', to: urls.organizationBilling() }}>
                    Your plan captures heatmaps on up to {captureUrlLimit} URLs. Pick the pages that matter most, or
                    upgrade to capture every page.
                </LemonBanner>
            )}

            {settings.enforcement_enabled ? (
                emptyAllowlist && (
                    <LemonBanner type="warning">
                        No URLs are listed, so no heatmap data is being collected. Add at least one URL
                        {canCaptureAllUrls ? ', or choose Allow all URLs' : ''}.
                    </LemonBanner>
                )
            ) : (
                <LemonBanner type="info">
                    These rules are not enforced yet. Heatmap data is still collected from every page for now, but that
                    will change. Set them up so capture keeps working when they take effect.
                </LemonBanner>
            )}

            <div className="flex flex-col gap-2">
                <LemonLabel>Pages to capture</LemonLabel>
                <LemonSegmentedButton
                    value={captureMode}
                    onChange={(value) => setCaptureMode(value as typeof captureMode)}
                    disabledReason={restrictedReason || undefined}
                    options={[
                        { value: 'url_allowlist', label: 'Only listed URLs' },
                        {
                            value: 'all',
                            label: 'Allow all URLs',
                            disabledReason: canCaptureAllUrls ? undefined : 'Upgrade to capture all pages',
                        },
                    ]}
                />
            </div>

            {isAllowlist && (
                <div className="flex flex-col gap-2">
                    <LemonLabel>Allowed URLs</LemonLabel>
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={urlAllowlist}
                        options={urlAllowlist.map((url) => ({ key: url, label: url }))}
                        onChange={(value) =>
                            setUrlAllowlist(captureUrlLimit != null ? value.slice(0, captureUrlLimit) : value)
                        }
                        placeholder="https://example.com/pricing"
                        limit={captureUrlLimit ?? undefined}
                        disabled={!!restrictedReason || settingsLoading}
                        data-attr="heatmap-capture-url-allowlist"
                    />
                    <p className="text-secondary mb-0">
                        {captureUrlLimit != null ? `Your plan captures up to ${captureUrlLimit} URLs. ` : ''}
                        Enter full URLs. Use <code>*</code> to match any characters, for example{' '}
                        <code>https://example.com/docs/*</code>.
                    </p>
                </div>
            )}

            {!canCaptureAllUrls && isAllowlist && (
                <div className="flex flex-col gap-2">
                    <LemonLabel>Pages that will stop capturing</LemonLabel>
                    {pagesLoading ? (
                        <LemonSkeleton className="h-16" />
                    ) : pagesError ? (
                        <LemonBanner type="error" action={{ children: 'Retry', onClick: loadPages }}>
                            Could not check which pages your listed URLs cover. Try again.
                        </LemonBanner>
                    ) : disabledPages.length === 0 ? (
                        <p className="text-secondary mb-0">
                            Your listed URLs cover every page we currently collect heatmaps on.
                        </p>
                    ) : (
                        <ul className="flex flex-col gap-1 m-0 p-0 border rounded divide-y">
                            {disabledPages.map((page) => (
                                <li
                                    key={page.url}
                                    className="flex items-center justify-between gap-2 list-none px-3 py-2"
                                >
                                    <span className="truncate">{page.url}</span>
                                    <span className="text-secondary whitespace-nowrap">
                                        {page.count.toLocaleString()} events
                                    </span>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}

            {saveError && (
                <LemonBanner type="error">
                    Could not save. Check that each entry is a full http or https URL, then try again.
                </LemonBanner>
            )}

            {!restrictedReason && (
                <LemonButton
                    className="self-start"
                    type="primary"
                    onClick={saveSettings}
                    loading={settingsLoading}
                    disabled={!hasChanges}
                >
                    Save capture URLs
                </LemonButton>
            )}
        </div>
    )
}
