import { SceneExport } from 'scenes/sceneTypes'

// import { useActions, useValues } from 'kea' // Uncomment if you use actions/values from logic
import { someLogic } from './someLogic'

export const scene: SceneExport = {
    component: VisionHogScene,
    logic: someLogic,
}

export function VisionHogScene(): JSX.Element {
    // const { isLoadingTempBackend, tempBackendData, tempBackendError } = useValues(someLogic)
    // const { loadTempBackendData } = useActions(someLogic)

    return (
        <div>
            <h1>Welcome to VisionHog!</h1>
            <p>This is a placeholder scene for the VisionHog product.</p>
            <p>
                To connect to your temporary backend endpoint (e.g., <code>/api/visionhog/temp_endpoint</code>), you can
                uncomment the example code in <code>someLogic.ts</code> and here to trigger a data load.
            </p>

            {/* Example of how to display loaded data or call an action
            <button onClick={loadTempBackendData} disabled={isLoadingTempBackend}>
                {isLoadingTempBackend ? 'Loading data...' : 'Load Temp Data'}
            </button>
            {tempBackendError && <p style={{ color: 'red' }}>Error: {tempBackendError}</p>}
            {tempBackendData && (
                <pre>
                    <strong>Data from backend:</strong>
                    {JSON.stringify(tempBackendData, null, 2)}
                </pre>
            )}
            */}
        </div>
    )
}
