import { useActions, useValues } from 'kea'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, cn } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { QuillSceneHeader } from '~/layout/scenes/components/QuillSceneHeader'
import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { COMMAND_CENTER_LAYOUTS, CommandCenterLayout, layoutColumns } from './commandCenterGrid'
import { commandCenterSceneLogic } from './commandCenterSceneLogic'
import { CommandCenterTile } from './CommandCenterTile'

export const scene: SceneExport = {
    component: CommandCenterScene,
    logic: commandCenterSceneLogic,
}

const LAYOUT_OPTIONS = COMMAND_CENTER_LAYOUTS.map((layout) => ({ label: layout, value: layout }))

// Tiles stack in a narrow scene and spread into the chosen columns as the scene gets wider.
const COLUMN_CLASSES: Record<number, string> = {
    1: '',
    2: '@min-[40rem]/command-center:grid-cols-2',
    3: '@min-[40rem]/command-center:grid-cols-2 @min-[64rem]/command-center:grid-cols-3',
}

export function CommandCenterScene(): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    const { layout, cells } = useValues(commandCenterSceneLogic)
    const { setLayout } = useActions(commandCenterSceneLogic)

    if (!enabled) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent className="h-full min-h-0 gap-y-0">
            <QuillSceneHeader
                title={<h1 className="m-0 min-w-0 truncate text-base font-bold text-foreground">Command center</h1>}
                actions={
                    <Select<CommandCenterLayout>
                        items={LAYOUT_OPTIONS}
                        value={layout}
                        onValueChange={(nextLayout: CommandCenterLayout | null) => {
                            if (nextLayout) {
                                setLayout(nextLayout)
                            }
                        }}
                    >
                        <SelectTrigger size="sm" aria-label="Layout" data-attr="command-center-layout">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {LAYOUT_OPTIONS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                }
            />
            <div className="@container/command-center min-h-0 flex-1 overflow-y-auto p-2" data-quill>
                {/* A tile needs about 24rem of height to show a chat and its composer, so short windows scroll instead. */}
                <div
                    className={cn(
                        'grid min-h-full auto-rows-[minmax(24rem,1fr)] gap-2',
                        COLUMN_CLASSES[layoutColumns(layout)]
                    )}
                >
                    {cells.map((_, index) => (
                        <CommandCenterTile key={index} index={index} />
                    ))}
                </div>
            </div>
        </SceneContent>
    )
}
