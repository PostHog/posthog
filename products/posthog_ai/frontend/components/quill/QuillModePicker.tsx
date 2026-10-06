import { useValues } from 'kea'
import { useState } from 'react'

import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
    ItemContent,
    ItemDescription,
    ItemRadio,
    ItemTitle,
    MenuLabel,
} from '@posthog/quill-primitives'

import { TodaySheetMenu } from '~/layout/today/TodaySheetMenu'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { getModeOption, MODE_OPTIONS, type PermissionMode } from 'products/posthog_ai/frontend/utils/composerModes'
import {
    CodexTaskRunCreateSchemaInitialPermissionModeEnumApi,
    InitialPermissionModeEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

const UNSUPERVISED_MODES: PermissionMode[] = [
    InitialPermissionModeEnumApi.BypassPermissions,
    CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.FullAccess,
]

export interface QuillModePickerProps {
    selectedMode: PermissionMode
    onModeChange: (mode: PermissionMode) => void
    modes: PermissionMode[]
}

export function QuillModePicker({ selectedMode, onModeChange, modes }: QuillModePickerProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const options = modes.flatMap((mode) => MODE_OPTIONS.filter((option) => option.value === mode))
    const selectedLabel = getModeOption(selectedMode)?.label ?? 'Mode'
    const unsupervised = UNSUPERVISED_MODES.includes(selectedMode)
    const { todayRailEnabled, phoneLayout } = useValues(todayShellLogic)

    if (todayRailEnabled && phoneLayout) {
        return (
            <>
                <Button
                    type="button"
                    variant={unsupervised ? 'destructive' : 'default'}
                    size="lg"
                    aria-label="Mode"
                    title={selectedLabel}
                    onClick={() => setOpen(true)}
                >
                    <span className="max-w-24 truncate">{selectedLabel}</span>
                </Button>
                <TodaySheetMenu open={open} onOpenChange={setOpen} title="Mode">
                    {options.map((option) => (
                        <ItemRadio
                            key={option.value}
                            aria-checked={option.value === selectedMode}
                            onClick={() => {
                                onModeChange(option.value)
                                setOpen(false)
                            }}
                            data-attr={`composer-mode-${option.value}`}
                        >
                            <ItemContent className="text-left">
                                <ItemTitle>{option.label}</ItemTitle>
                                <ItemDescription className="line-clamp-none">{option.description}</ItemDescription>
                            </ItemContent>
                        </ItemRadio>
                    ))}
                </TodaySheetMenu>
            </>
        )
    }

    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <DropdownMenuTrigger
                render={
                    <Button
                        type="button"
                        variant={unsupervised ? 'destructive' : 'default'}
                        size="sm"
                        aria-label="Mode"
                        title={selectedLabel}
                    >
                        <span className="@max-[400px]/composer:max-w-20 truncate">{selectedLabel}</span>
                    </Button>
                }
            />
            <DropdownMenuContent align="start" side="top" sideOffset={6} className="min-w-[200px]">
                <MenuLabel>Mode</MenuLabel>
                <DropdownMenuRadioGroup
                    value={selectedMode}
                    // Applied on pick, not after the menu closes: a message sent during the close would
                    // otherwise still run in the old mode, which may skip the approval just chosen.
                    onValueChange={(value) => {
                        onModeChange(value as PermissionMode)
                        setOpen(false)
                    }}
                >
                    {options.map((option) => (
                        <DropdownMenuRadioItem key={option.value} value={option.value}>
                            <span className="whitespace-nowrap">{option.label}</span>
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
