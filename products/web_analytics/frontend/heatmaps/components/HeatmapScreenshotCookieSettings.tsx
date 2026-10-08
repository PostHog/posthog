import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDialog, LemonInputSelect, LemonLabel, LemonSkeleton } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { HEATMAP_SCREENSHOT_COOKIE_NAME } from '../heatmapScreenshotCookie'
import { heatmapScreenshotSettingsLogic } from './heatmapScreenshotSettingsLogic'

export function HeatmapScreenshotCookieSettings(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = heatmapScreenshotSettingsLogic({ teamId: currentTeamId ?? 0 })
    const {
        settings,
        settingsLoading,
        hostnames,
        secret,
        rotatedSecretLoading,
        suggestions,
        hasChanges,
        loadError,
        saveError,
    } = useValues(logic)
    const { loadSettings, setHostnames, saveSettings, rotateSecret } = useActions(logic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (loadError) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadSettings }}>
                Could not load screenshot settings. Try again.
            </LemonBanner>
        )
    }
    if (!settings) {
        return <LemonSkeleton />
    }

    return (
        <div className="flex flex-col gap-3 max-w-160">
            {!settings.cookie_delivery_enabled && (
                <LemonBanner type="info">
                    Screenshot cookie delivery is disabled on this installation. You can save your settings, but
                    screenshots will run without the cookie. Contact your PostHog administrator to enable delivery.
                </LemonBanner>
            )}
            <p className="mb-0">
                Allow screenshots of public pages behind bot protection. Approve the hostnames that may receive this
                project's screenshot cookie, then add a matching exception in your bot protection settings.
            </p>
            {!settings.allowed_hostnames.length && (
                <LemonBanner type="info">
                    No hostnames are approved, so screenshots run without a bypass cookie. Ask a project admin to
                    approve each hostname that needs one, including redirect destinations.
                    {settings.has_secret && (
                        <p className="mb-0 mt-2">
                            A value already exists. If you used it before approving hostnames, rotate it and replace the
                            old value in your bot protection rule.
                        </p>
                    )}
                </LemonBanner>
            )}
            <div className="flex flex-col gap-2">
                <LemonLabel>Approved screenshot hostnames</LemonLabel>
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={hostnames}
                    options={suggestions.map((hostname) => ({ key: hostname, label: hostname }))}
                    onChange={setHostnames}
                    placeholder="www.example.com"
                    disabled={!!restrictedReason || settingsLoading || rotatedSecretLoading}
                    data-attr="heatmap-screenshot-hostnames"
                />
                <p className="text-secondary mb-0">
                    Enter exact hostnames without a URL or wildcard. Approving www.example.com does not approve
                    example.com or its other subdomains. Toolbar URL suggestions require your selection and approval.
                </p>
                {saveError && (
                    <LemonBanner type="error">
                        Could not save hostnames. Check that each entry is an exact DNS hostname without a URL, port,
                        wildcard, or IP address, then try again.
                    </LemonBanner>
                )}
                {!restrictedReason && (
                    <LemonButton
                        className="self-start"
                        type="primary"
                        onClick={saveSettings}
                        loading={settingsLoading}
                        disabled={!hasChanges || rotatedSecretLoading}
                    >
                        Save approved hostnames
                    </LemonButton>
                )}
            </div>
            <LemonLabel>Screenshot cookie</LemonLabel>
            {restrictedReason ? (
                <p className="mb-0">
                    {settings.has_secret
                        ? 'A screenshot value is configured. Only project admins can view or rotate it.'
                        : 'No screenshot value is configured. Ask a project admin to generate one.'}
                </p>
            ) : (
                <>
                    {secret && (
                        <CodeSnippet
                            className="ph-no-capture ph-replay-block"
                            language={Language.HTTP}
                            thing="cookie"
                        >{`Cookie: ${HEATMAP_SCREENSHOT_COOKIE_NAME}=${secret}`}</CodeSnippet>
                    )}
                    <div>
                        <LemonButton
                            type="secondary"
                            loading={rotatedSecretLoading}
                            disabledReason={
                                !settings.allowed_hostnames.length
                                    ? 'Save at least one approved hostname first.'
                                    : settingsLoading || hasChanges
                                      ? 'Save your hostname changes first.'
                                      : undefined
                            }
                            onClick={() => {
                                if (!settings.has_secret) {
                                    rotateSecret()
                                    return
                                }
                                LemonDialog.open({
                                    title: 'Rotate the screenshot value?',
                                    description:
                                        'New screenshots will use the new value. Replace the old value in your bot protection rule to restore access and revoke the old value.',
                                    primaryButton: { children: 'Rotate value', onClick: rotateSecret },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                        >
                            {settings.has_secret ? 'Rotate value' : 'Generate screenshot value'}
                        </LemonButton>
                    </div>
                </>
            )}
            <p className="mb-0">
                Match the exact cookie value and approved hostname in your rule. Exempt only the bot checks that block
                screenshots. Keep authentication, rate limits, and other security rules enabled.
            </p>
            <p className="text-secondary mb-0">
                The rendering service and approved HTTPS hosts receive this credential. It stays usable until you remove
                it from your bot protection rule, even after rotating it here. Hostname approval does not restrict paths
                or ports. Screenshots cannot use it to log in.
            </p>
        </div>
    )
}
