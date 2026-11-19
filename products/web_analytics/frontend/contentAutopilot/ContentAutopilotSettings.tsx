import { LemonCard } from '@posthog/lemon-ui'

import { AiVisibilityBrandsSetting } from './AiVisibilityBrandsSetting'
import { AiVisibilityEnginesSetting } from './AiVisibilityEnginesSetting'
import { ContentAutopilotSetup } from './ContentAutopilotSetup'

export const ContentAutopilotSettings = (): JSX.Element => {
    return (
        <div className="flex flex-col gap-4" data-attr="content-autopilot-settings-sections">
            <ContentAutopilotSetup />
            <LemonCard hoverEffect={false} className="w-full max-w-3xl p-4" data-attr="content-autopilot-brands-card">
                <h3 className="m-0">Brands</h3>
                <p className="m-0 mt-1 mb-4 text-secondary">
                    Label the companies behind the sites AI answers cite. The competitors you confirm are the ones
                    Rankings compares you against.
                </p>
                <AiVisibilityBrandsSetting />
            </LemonCard>
            <LemonCard hoverEffect={false} className="w-full max-w-3xl p-4" data-attr="content-autopilot-engines-card">
                <h3 className="m-0">Engines</h3>
                <p className="m-0 mt-1 mb-4 text-secondary">
                    Choose which AI engines answer your tracked prompts, and how often. Each engine gets its own column
                    in AI visibility.
                </p>
                <AiVisibilityEnginesSetting />
            </LemonCard>
        </div>
    )
}
