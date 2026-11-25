import { IconGear } from '@posthog/icons'
import { Button, Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import type { ContentAutopilotWorkspaceTab } from './contentAutopilotLogic'

export interface ContentAutopilotWorkspaceTabDefinition {
    key: Exclude<ContentAutopilotWorkspaceTab, 'settings'>
    label: string
    content: JSX.Element
}

export const QuillContentAutopilotWorkspaceTabs = ({
    tabs,
    activeKey,
    onChange,
    onOpenSettings,
}: {
    tabs: ContentAutopilotWorkspaceTabDefinition[]
    activeKey: ContentAutopilotWorkspaceTab
    onChange: (tab: ContentAutopilotWorkspaceTab) => void
    /** Absent until a site is set up, because settings belong to a site. */
    onOpenSettings?: () => void
}): JSX.Element => (
    <Tabs
        value={activeKey}
        onValueChange={(value) => onChange(value as ContentAutopilotWorkspaceTab)}
        className="flex flex-col gap-4"
        data-attr="content-autopilot-workspace-tabs"
    >
        <div className="flex flex-wrap items-center justify-between gap-2">
            <TabsList variant="line">
                {tabs.map(({ key, label }) => (
                    <TabsTrigger key={key} value={key}>
                        {label}
                    </TabsTrigger>
                ))}
            </TabsList>
            {onOpenSettings ? (
                <Button
                    variant="outline"
                    size="icon"
                    onClick={onOpenSettings}
                    tooltip="Settings"
                    aria-label="Settings"
                    data-attr="content-autopilot-settings"
                >
                    <IconGear />
                </Button>
            ) : null}
        </div>
        {tabs.map(({ key, content }) => (
            <TabsContent key={key} value={key}>
                {content}
            </TabsContent>
        ))}
    </Tabs>
)
