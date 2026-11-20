import {
    Button,
    Field,
    FieldDescription,
    FieldLabel,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    Text,
} from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'

import type { HeatmapScreenshotSettingsApi } from '../../generated/api.schemas'
import { HEATMAP_SCREENSHOT_COOKIE_NAME } from '../heatmapScreenshotCookie'

export function QuillHeatmapScreenshotCookieSettings({
    settings,
    settingsLoading,
    hostnames,
    secret,
    rotatedSecretLoading,
    suggestions,
    hasChanges,
    saveError,
    restrictedReason,
    rotateDisabledReason,
    onHostnamesChange,
    onSave,
    onRotate,
}: {
    settings: HeatmapScreenshotSettingsApi
    settingsLoading: boolean
    hostnames: string[]
    secret: string | null
    rotatedSecretLoading: boolean
    suggestions: string[]
    hasChanges: boolean
    saveError: string | null
    restrictedReason: string | null
    rotateDisabledReason: string | undefined
    onHostnamesChange: (hostnames: string[]) => void
    onSave: () => void
    onRotate: () => void
}): JSX.Element {
    return (
        <div className="flex max-w-160 flex-col gap-4">
            {!settings.cookie_delivery_enabled && (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Screenshot cookie delivery is disabled on this installation. You can save your settings, but
                            screenshots will run without the cookie. Contact your PostHog administrator to enable
                            delivery.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}
            <Text size="xs" render={<p className="m-0" />}>
                Allow screenshots of public pages behind bot protection. Approve the hostnames that may receive this
                project's screenshot cookie, then add a matching exception in your bot protection settings.
            </Text>
            {!settings.allowed_hostnames.length && (
                <Item tone="info" size="sm">
                    <ItemContent className="gap-2">
                        <ItemDescription>
                            No hostnames are approved, so screenshots run without a bypass cookie. Ask a project admin
                            to approve each hostname that needs one, including redirect destinations.
                        </ItemDescription>
                        {settings.has_secret && (
                            <ItemDescription>
                                A value already exists. If you used it before approving hostnames, rotate it and replace
                                the old value in your bot protection rule.
                            </ItemDescription>
                        )}
                    </ItemContent>
                </Item>
            )}
            <div className="flex flex-col gap-2">
                <Field>
                    <FieldLabel>Approved screenshot hostnames</FieldLabel>
                    <TagsCombobox
                        value={hostnames}
                        options={suggestions}
                        onChange={onHostnamesChange}
                        customValueNoun="hostname"
                        dataAttr="heatmap-screenshot-hostnames"
                        placeholder="www.example.com"
                        disabled={settingsLoading || rotatedSecretLoading}
                        disabledReason={restrictedReason}
                        className="w-full"
                    />
                    <FieldDescription>
                        Enter exact hostnames without a URL or wildcard. Approving www.example.com does not approve
                        example.com or its other subdomains. Toolbar URL suggestions require your selection and
                        approval.
                    </FieldDescription>
                </Field>
                {saveError && (
                    <Item tone="destructive" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                Could not save hostnames. Check that each entry is an exact DNS hostname without a URL,
                                port, wildcard, or IP address, then try again.
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                )}
                {!restrictedReason && (
                    <div>
                        <Button
                            variant="primary"
                            onClick={onSave}
                            loading={settingsLoading}
                            disabled={rotatedSecretLoading}
                            disabledReason={!hasChanges ? 'No changes to save' : undefined}
                        >
                            Save approved hostnames
                        </Button>
                    </div>
                )}
            </div>
            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Screenshot cookie
                </Heading>
                {restrictedReason ? (
                    <Text size="xs" render={<p className="m-0" />}>
                        {settings.has_secret
                            ? 'A screenshot value is configured. Only project admins can view or rotate it.'
                            : 'No screenshot value is configured. Ask a project admin to generate one.'}
                    </Text>
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
                            <Button
                                variant="outline"
                                loading={rotatedSecretLoading}
                                disabledReason={rotateDisabledReason}
                                onClick={onRotate}
                            >
                                {settings.has_secret ? 'Rotate value' : 'Generate screenshot value'}
                            </Button>
                        </div>
                    </>
                )}
            </div>
            <Text size="xs" render={<p className="m-0" />}>
                Match the exact cookie value and approved hostname in your rule. Exempt only the bot checks that block
                screenshots. Keep authentication, rate limits, and other security rules enabled.
            </Text>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                The rendering service and approved HTTPS hosts receive this credential. It stays usable until you remove
                it from your bot protection rule, even after rotating it here. Hostname approval does not restrict paths
                or ports. Screenshots cannot use it to log in.
            </Text>
        </div>
    )
}
