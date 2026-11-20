import type { PostHogSessionReplayConfig } from 'posthog-react-native'

export const DEMO_REPLAY_CONFIG: PostHogSessionReplayConfig = {
    maskAllTextInputs: true,
    maskAllImages: true,
    maskAllSandboxedViews: true,
    captureLog: false,
    captureNetworkTelemetry: false,
    captureTouches: false,
    throttleDelayMs: 1000,
}

interface Recorder {
    startSessionRecording: () => Promise<void>
    stopSessionRecording: () => Promise<void>
}

export class DemoReplay {
    private allowed = false

    constructor(private readonly recorder: Recorder) {}

    setAllowed(allowed: boolean): void {
        if (allowed === this.allowed) {
            return
        }
        this.allowed = allowed
        if (allowed) {
            void this.recorder.startSessionRecording().catch(() => {
                this.allowed = false
                void this.recorder.stopSessionRecording().catch(() => undefined)
            })
        } else {
            // Stop immediately because the SDK also cancels pending starts and retries.
            void this.recorder.stopSessionRecording().catch(() => undefined)
        }
    }
}
