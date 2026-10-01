import { useRef, useState } from 'react'

import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
    MenuLabel,
} from '@posthog/quill-primitives'

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
    // Applied once the menu has closed, so the toolbar doesn't relayout under the closing menu.
    const pendingModeRef = useRef<PermissionMode | null>(null)
    const options = modes.flatMap((mode) => MODE_OPTIONS.filter((option) => option.value === mode))
    const selectedLabel = getModeOption(selectedMode)?.label ?? 'Mode'
    const unsupervised = UNSUPERVISED_MODES.includes(selectedMode)

    return (
        <DropdownMenu
            open={open}
            onOpenChange={setOpen}
            onOpenChangeComplete={(isOpen) => {
                if (!isOpen && pendingModeRef.current !== null) {
                    onModeChange(pendingModeRef.current)
                    pendingModeRef.current = null
                }
            }}
        >
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
                    onValueChange={(value) => {
                        pendingModeRef.current = value as PermissionMode
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
