import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

// Shared fallback for the scanner editor and detail scenes when the scanner GET fails or times out,
// instead of a bare "Loading…" title or a silent bounce to the empty landing page.
export function ScannerLoadError({ onRetry }: { onRetry: () => void }): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection name="Couldn't load scanner" resourceType={{ type: 'replay_vision' }} />
            <div className="flex flex-col items-center gap-4 py-16 text-center">
                <p className="text-muted max-w-md m-0">
                    Something went wrong loading this scanner. It's usually temporary, so try again or head back to your
                    scanners.
                </p>
                <div className="flex gap-2">
                    <LemonButton type="primary" onClick={onRetry} data-attr="vision-scanner-load-retry">
                        Try again
                    </LemonButton>
                    <LemonButton type="secondary" to={urls.replayVision()} data-attr="vision-scanner-load-back">
                        Back to scanners
                    </LemonButton>
                </div>
            </div>
        </SceneContent>
    )
}
