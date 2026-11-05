import { useValues } from 'kea'

import { LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotSetup } from './ContentAutopilotSetup'

// Prompt tracking and bots work without a site. Only content autopilot tabs need one.
export const ContentAutopilotSiteGate = ({ children }: { children: JSX.Element }): JSX.Element => {
    const { profile, profileDataLoaded, workspaceErrors, workspaceInitialized } = useValues(contentAutopilotLogic)

    if (!workspaceInitialized) {
        return <LemonSkeleton className="h-72 w-full" />
    }
    if (workspaceErrors.profiles && !profile) {
        return (
            <LemonCard hoverEffect={false} className="p-8 text-center">
                <h2>Sites could not be loaded</h2>
                <p className="text-muted">Try again before adding or changing a site.</p>
            </LemonCard>
        )
    }
    if (!profile) {
        return <ContentAutopilotSetup onboarding />
    }
    if (!profileDataLoaded) {
        return <LemonSkeleton className="h-72 w-full" />
    }
    return children
}
