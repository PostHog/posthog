import { IconCode } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { RecommendationTile } from '../RecommendationTile'

interface SourceMapsData {
    unresolvedFrames: number
    totalFrames: number
    affectedIssues: number
}

export function SourceMapsTile({ data }: { data: SourceMapsData }): JSX.Element {
    const percentage = data.totalFrames > 0 ? Math.round((data.unresolvedFrames / data.totalFrames) * 100) : 0

    return (
        <RecommendationTile
            tileId="source-maps"
            icon={<IconCode className="text-warning" />}
            title="Unresolved source maps detected"
            category="Source maps"
            priority="important"
            actions={
                <>
                    <LemonButton
                        type="primary"
                        size="small"
                        to="https://posthog.com/docs/error-tracking/source-maps"
                        targetBlank
                    >
                        Upload source maps
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size="small"
                        to="https://posthog.com/docs/error-tracking/source-maps"
                        targetBlank
                    >
                        View docs
                    </LemonButton>
                </>
            }
        >
            <p>
                Without source maps, stack traces show minified code that's nearly impossible to debug. Upload your
                source maps to see the original file names, line numbers, and function names.
            </p>

            <div className="flex gap-3 mt-2">
                <div className="flex-1 bg-surface-alt rounded-lg px-3 py-2 text-center">
                    <span className="text-xl font-bold text-warning">{percentage}%</span>
                    <p className="text-xs text-secondary mb-0">frames unresolved</p>
                </div>
                <div className="flex-1 bg-surface-alt rounded-lg px-3 py-2 text-center">
                    <span className="text-xl font-bold">{data.unresolvedFrames}</span>
                    <p className="text-xs text-secondary mb-0">unresolved frames</p>
                </div>
                <div className="flex-1 bg-surface-alt rounded-lg px-3 py-2 text-center">
                    <span className="text-xl font-bold">{data.affectedIssues}</span>
                    <p className="text-xs text-secondary mb-0">affected issues</p>
                </div>
            </div>

            <div className="rounded-lg border border-border bg-surface-alt px-3 py-2 mt-2">
                <p className="text-xs mb-0">
                    <strong>Quick start:</strong> Use the{' '}
                    <Link to="https://posthog.com/docs/error-tracking/source-maps" targetBlank>
                        PostHog CLI
                    </Link>{' '}
                    or integrate source map uploads into your CI/CD pipeline for automatic uploads on each deploy.
                </p>
            </div>
        </RecommendationTile>
    )
}
