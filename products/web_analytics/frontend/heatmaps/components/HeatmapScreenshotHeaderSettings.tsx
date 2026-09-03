import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDialog, Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import {
    HEATMAP_SCREENSHOT_HEADER,
    HEATMAP_SCREENSHOT_HEADER_DEFAULT_VALUE,
    heatmapScreenshotHeaderValue,
} from '../heatmapScreenshotHeader'

export function HeatmapScreenshotHeaderSettings(): JSX.Element {
    const { currentTeam, currentTeamId } = useValues(teamLogic)
    const { loadCurrentTeam } = useActions(teamLogic)
    const [rotating, setRotating] = useState(false)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const headerValue = heatmapScreenshotHeaderValue(currentTeam)
    const usesDefault = headerValue === HEATMAP_SCREENSHOT_HEADER_DEFAULT_VALUE

    const rotate = async (): Promise<void> => {
        setRotating(true)
        try {
            await api.update(`api/environments/${currentTeamId}/rotate_heatmaps_screenshot_secret`, {})
            loadCurrentTeam()
            lemonToast.success('New header value ready. Update your rule to match it.')
        } catch {
            lemonToast.error('Could not generate a new header value. Please try again.')
        } finally {
            setRotating(false)
        }
    }

    return (
        <div className="flex flex-col gap-2">
            <p className="mb-0">
                The screenshots come from a rendering service, not from PostHog's own IP addresses, so an IP allowlist
                cannot let them through. Every screenshot request carries the header below. Add a rule to your WAF or
                bot protection that permits it.
            </p>
            <CodeSnippet language={Language.HTTP} thing="header">
                {`${HEATMAP_SCREENSHOT_HEADER}: ${headerValue}`}
            </CodeSnippet>
            <p className="mb-0">
                {usesDefault
                    ? 'This project uses the public default value, which anyone can send. Generate a value only this project knows, so your rule permits our screenshots alone.'
                    : 'This value is private to this project. Rotate it if it leaks. The old value stops working at once, so update your rule straight after.'}
            </p>
            <p className="text-secondary mb-0">
                The rendering service puts the header on every request the page makes, third-party hosts included. Treat
                the value as a shared secret of modest worth: it permits a page load, and nothing else. Read more in our{' '}
                <Link to="https://posthog.com/docs/toolbar/heatmaps">heatmaps docs</Link>.
            </p>
            <div>
                <LemonButton
                    type="secondary"
                    disabledReason={restrictedReason}
                    loading={rotating}
                    onClick={() => {
                        if (usesDefault) {
                            void rotate()
                            return
                        }
                        LemonDialog.open({
                            title: 'Rotate the header value?',
                            description:
                                'Screenshots start sending the new value at once. Any rule that matches the current value stops permitting them until you update it.',
                            primaryButton: { children: 'Rotate value', onClick: () => void rotate() },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }}
                >
                    {usesDefault ? 'Generate a value for this project' : 'Rotate value'}
                </LemonButton>
            </div>
        </div>
    )
}
