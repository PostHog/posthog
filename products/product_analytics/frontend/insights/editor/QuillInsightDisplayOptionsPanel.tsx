import { IconInfo } from '@posthog/icons'
import {
    FieldLegend,
    FieldSet,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { DisplayOptionSection, DisplayOptionTab, DisplayOptionTabKey } from './insightDisplayOptions'

function QuillDisplayOptionSectionList({ sections }: { sections: DisplayOptionSection[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            {sections.map((section) => (
                <FieldSet key={section.key} className="gap-2">
                    {section.title && (
                        <FieldLegend variant="label" className="flex items-center gap-1" data-attr={section.dataAttr}>
                            {section.title}
                            {section.tooltip && (
                                <Tooltip>
                                    <TooltipTrigger render={<span className="inline-flex text-muted-foreground" />}>
                                        <IconInfo />
                                    </TooltipTrigger>
                                    <TooltipContent className="max-w-64">{section.tooltip}</TooltipContent>
                                </Tooltip>
                            )}
                        </FieldLegend>
                    )}
                    <div className="flex flex-col gap-2" data-attr={section.title ? undefined : section.dataAttr}>
                        {section.items.map((Item, index) => (
                            <Item key={index} />
                        ))}
                    </div>
                </FieldSet>
            ))}
        </div>
    )
}

export interface QuillInsightDisplayOptionsPanelProps {
    tabs: DisplayOptionTab[]
    activeTab: DisplayOptionTab
    onTabChange: (key: DisplayOptionTabKey) => void
}

export function QuillInsightDisplayOptionsPanel({
    tabs,
    activeTab,
    onTabChange,
}: QuillInsightDisplayOptionsPanelProps): JSX.Element {
    if (tabs.length === 1) {
        return (
            <div className="w-80 p-2" data-attr="insight-display-options-panel">
                <QuillDisplayOptionSectionList sections={activeTab.sections} />
            </div>
        )
    }

    return (
        <Tabs
            value={activeTab.key}
            onValueChange={(key) => onTabChange(key as DisplayOptionTabKey)}
            className="w-80 gap-3 p-2"
            data-attr="insight-display-options-panel"
        >
            <TabsList variant="line" className="w-full" data-attr="insight-display-options-tabs">
                {tabs.map((tab) => (
                    <TabsTrigger key={tab.key} value={tab.key} data-attr={`insight-display-options-tab-${tab.key}`}>
                        {tab.label}
                    </TabsTrigger>
                ))}
            </TabsList>
            {tabs.map((tab) => (
                <TabsContent key={tab.key} value={tab.key}>
                    <QuillDisplayOptionSectionList sections={tab.sections} />
                </TabsContent>
            ))}
        </Tabs>
    )
}
