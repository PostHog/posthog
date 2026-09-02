import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SceneExport } from 'scenes/sceneTypes'

import { HeatmapRecording } from '../../components/HeatmapRecording'
import { heatmapRecordingLogic } from './heatmapRecordingLogic'

export const scene: SceneExport = {
    component: HeatmapRecordingScene,
    logic: heatmapRecordingLogic,
}

export function HeatmapRecordingScene(): JSX.Element {
    return (
        <div>
            <LemonBanner
                type="info"
                dismissKey="heatmaps-beta-banner"
                className="mb-4"
                action={{ children: 'Send feedback', id: 'heatmaps-feedback-button' }}
            >
                <p>
                    Heatmaps is in beta. Please let us know what you'd like to see here and/or report any issues
                    directly to us!
                </p>
            </LemonBanner>
            <HeatmapRecording />
        </div>
    )
}
