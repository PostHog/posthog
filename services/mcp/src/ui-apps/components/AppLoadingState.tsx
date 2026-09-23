import type { ReactElement } from 'react'

import { PostHogLogo } from './PostHogLogo'

export function AppLoadingState(): ReactElement {
    return (
        <div className="flex flex-col items-center justify-center h-[200px]">
            <div className="[animation:loading__pulse_2s_ease-in-out_infinite]">
                <PostHogLogo size={40} />
            </div>
        </div>
    )
}
