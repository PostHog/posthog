import { Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import type { ContentAutopilotWorkspaceTab } from './contentAutopilotLogic'

export interface ContentAutopilotWorkspaceTabDefinition {
    key: ContentAutopilotWorkspaceTab
    label: string
    content: JSX.Element
    'data-attr'?: string
}

export const ContentAutopilotWorkspaceTabs = ({
    tabs,
    activeKey,
    onChange,
}: {
    tabs: ContentAutopilotWorkspaceTabDefinition[]
    activeKey: ContentAutopilotWorkspaceTab
    onChange: (tab: ContentAutopilotWorkspaceTab) => void
}): JSX.Element => (
    <Tabs
        value={activeKey}
        onValueChange={(value) => onChange(value as ContentAutopilotWorkspaceTab)}
        className="flex flex-col gap-4"
        data-attr="content-autopilot-workspace-tabs"
    >
        <div className="overflow-x-auto">
            <TabsList variant="line">
                {tabs.map(({ key, label, 'data-attr': dataAttr }) => (
                    <TabsTrigger key={key} value={key} data-attr={dataAttr}>
                        {label}
                    </TabsTrigger>
                ))}
            </TabsList>
        </div>
        {tabs.map(({ key, content }) => (
            <TabsContent key={key} value={key}>
                {content}
            </TabsContent>
        ))}
    </Tabs>
)
