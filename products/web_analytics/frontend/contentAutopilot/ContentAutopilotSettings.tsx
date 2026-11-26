import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@posthog/quill'

import { AiVisibilityBrandsSetting } from './AiVisibilityBrandsSetting'
import { AiVisibilityEnginesSetting } from './AiVisibilityEnginesSetting'
import { ContentAutopilotSetup } from './ContentAutopilotSetup'

const SECTIONS = [
    {
        title: 'Brands',
        description:
            'Label the companies behind the sites AI answers cite. The competitors you confirm are the ones Rankings compares you against.',
        dataAttr: 'content-autopilot-brands-card',
        content: <AiVisibilityBrandsSetting />,
    },
    {
        title: 'Engines',
        description:
            'Choose which AI engines answer your tracked prompts, and how often. Each engine gets its own column in AI visibility.',
        dataAttr: 'content-autopilot-engines-card',
        content: <AiVisibilityEnginesSetting />,
    },
]

export const ContentAutopilotSettings = (): JSX.Element => (
    <div className="flex flex-col gap-4" data-attr="content-autopilot-settings-sections">
        <ContentAutopilotSetup />
        {SECTIONS.map(({ title, description, dataAttr, content }) => (
            <Card key={title} className="w-full max-w-3xl" data-attr={dataAttr}>
                <CardHeader>
                    <CardTitle role="heading" aria-level={3}>
                        {title}
                    </CardTitle>
                    <CardDescription>{description}</CardDescription>
                </CardHeader>
                <CardContent>{content}</CardContent>
            </Card>
        ))}
    </div>
)
