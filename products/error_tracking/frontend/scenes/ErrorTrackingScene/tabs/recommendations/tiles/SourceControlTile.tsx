import { IconGithub, IconGitLab } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { RecommendationTile } from '../RecommendationTile'

export function SourceControlTile(): JSX.Element {
    return (
        <RecommendationTile
            tileId="source-control"
            icon={<IconGithub />}
            title="Connect your source control"
            category="Integration"
            priority="setup"
            actions={
                <LemonButton
                    type="secondary"
                    size="small"
                    to="https://posthog.com/docs/error-tracking/source-maps"
                    targetBlank
                >
                    Learn more
                </LemonButton>
            }
        >
            <p>
                Link your GitHub or GitLab repository to get richer context on errors — see exactly which commit
                introduced an issue, link stack frames to source code, and create issues directly from PostHog.
            </p>
            <div className="flex gap-2 mt-2">
                <div className="flex items-center gap-2 bg-surface-alt rounded-lg px-3 py-2 flex-1">
                    <IconGithub className="text-lg" />
                    <div className="flex-1">
                        <p className="text-sm font-medium mb-0">GitHub</p>
                        <p className="text-xs text-secondary mb-0">Not connected</p>
                    </div>
                    <LemonButton size="xsmall" type="primary">
                        Connect
                    </LemonButton>
                </div>
                <div className="flex items-center gap-2 bg-surface-alt rounded-lg px-3 py-2 flex-1">
                    <IconGitLab className="text-lg" />
                    <div className="flex-1">
                        <p className="text-sm font-medium mb-0">GitLab</p>
                        <p className="text-xs text-secondary mb-0">Not connected</p>
                    </div>
                    <LemonButton size="xsmall" type="primary">
                        Connect
                    </LemonButton>
                </div>
            </div>
        </RecommendationTile>
    )
}
