import { SceneExport } from 'scenes/sceneTypes'

import { HeatmapRecording } from '../../components/HeatmapRecording'
import { heatmapRecordingLogic } from './heatmapRecordingLogic'

export const scene: SceneExport = {
    component: HeatmapRecordingScene,
    logic: heatmapRecordingLogic,
}

export function HeatmapRecordingScene(): JSX.Element {
    return <HeatmapRecording />
}
