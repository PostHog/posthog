import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

export function QuillInsightSaveButton({
    saveAs,
    saveInsight,
    isSaved,
    insightSaving,
    insightChanged,
    addingToDashboard,
    onSaveAndAddToDashboard,
}: {
    saveAs: () => void
    saveInsight: (redirectToViewMode?: boolean) => void
    isSaved: boolean | undefined
    insightSaving: boolean
    insightChanged: boolean
    addingToDashboard: boolean
    onSaveAndAddToDashboard?: () => void
}): JSX.Element {
    const disabled = isSaved && !insightChanged
    const saveAsAvailable = isSaved && !addingToDashboard

    return (
        <ButtonGroup>
            <Button
                variant="primary"
                onClick={() => saveInsight(true)}
                data-attr="insight-save-button"
                disabled={disabled}
                loading={!disabled && insightSaving}
            >
                {disabled ? 'No changes' : addingToDashboard ? 'Save & add to dashboard' : 'Save'}
            </Button>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="primary"
                            size="icon"
                            aria-label="More save options"
                            data-attr="insight-save-dropdown"
                            disabled={disabled && !saveAsAvailable}
                        />
                    }
                >
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-56">
                    {!disabled && (
                        <DropdownMenuItem
                            onClick={() => saveInsight(false)}
                            data-attr="insight-save-and-continue"
                            disabled={insightSaving}
                        >
                            {addingToDashboard ? 'Save, add to dashboard' : 'Save'} & continue editing
                        </DropdownMenuItem>
                    )}
                    {!disabled && onSaveAndAddToDashboard && (
                        <DropdownMenuItem
                            onClick={() => onSaveAndAddToDashboard()}
                            data-attr="insight-save-and-add-to-dashboard"
                            disabled={insightSaving}
                        >
                            Save & add to dashboard…
                        </DropdownMenuItem>
                    )}
                    {saveAsAvailable && (
                        <DropdownMenuItem onClick={() => saveAs()} data-attr="insight-save-as-new-insight">
                            Save as…
                        </DropdownMenuItem>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        </ButtonGroup>
    )
}
