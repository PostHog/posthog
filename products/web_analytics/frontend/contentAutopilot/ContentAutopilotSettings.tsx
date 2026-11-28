import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@posthog/quill'

import { AiVisibilityAddBrandForm } from './AiVisibilityAddBrandForm'
import { AiVisibilityBrandsSetting } from './AiVisibilityBrandsSetting'
import { AiVisibilityEnginesSetting } from './AiVisibilityEnginesSetting'
import { AiVisibilityTopicsSetting } from './AiVisibilityTopicsSetting'

const SECTIONS = [
    {
        title: 'Brands',
        description:
            'Add your own site and your competitors, and label the companies behind the sites AI answers cite. The competitors you confirm are the ones Rankings compares you against.',
        dataAttr: 'content-autopilot-brands-card',
        content: (
            <>
                <div className="mb-4">
                    <AiVisibilityAddBrandForm formKey="settings" kinds={['own', 'competitor']} />
                </div>
                <AiVisibilityBrandsSetting />
            </>
        ),
    },
    {
        title: 'Topics',
        description:
            'Topics group your prompts in the overview and the prompt list. Rename, merge or remove a topic here, or set the topic of several prompts at once from the prompt list.',
        dataAttr: 'content-autopilot-topics-card',
        content: <AiVisibilityTopicsSetting />,
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
