import { ChangeEvent, useId } from 'react'

import {
    Button,
    Checkbox,
    Field,
    Label,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
    Textarea,
} from '@posthog/quill'

import { ReportNoteTargetOption } from '../../logics/reportNotesLogic'

export interface QuillReportNoteComposerProps {
    text: string
    onTextChange: (text: string) => void
    maxLength: number
    placeholder: string
    sendToScouts: boolean
    onSendToScoutsChange: (sendToScouts: boolean) => void
    sendToScoutsDisabledReason?: string
    skillName: string
    onSkillNameChange: (skillName: string) => void
    targetOptions: ReportNoteTargetOption[]
    targetOptionsLoading: boolean
    saving: boolean
    onCancel: () => void
    onSubmit: () => void
}

export function QuillReportNoteComposer({
    text,
    onTextChange,
    maxLength,
    placeholder,
    sendToScouts,
    onSendToScoutsChange,
    sendToScoutsDisabledReason,
    skillName,
    onSkillNameChange,
    targetOptions,
    targetOptionsLoading,
    saving,
    onCancel,
    onSubmit,
}: QuillReportNoteComposerProps): JSX.Element {
    const checkboxId = useId()

    return (
        <div className="flex flex-col gap-2">
            <Textarea
                value={text}
                disabled={saving}
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onTextChange(event.target.value)}
                placeholder={placeholder}
                aria-label="Add a note about this report"
                maxLength={maxLength}
                rows={2}
                autoFocus
                className="max-h-48 min-h-14! resize-none"
            />
            <div className="flex flex-wrap items-center gap-2">
                <Field orientation="horizontal" className="w-auto">
                    <Checkbox
                        id={checkboxId}
                        checked={sendToScouts}
                        disabled={!!sendToScoutsDisabledReason}
                        onCheckedChange={(value: boolean) => onSendToScoutsChange(value)}
                        data-attr="inbox-report-note-send-to-scouts"
                    />
                    <Label htmlFor={checkboxId}>Also send to the scouts</Label>
                </Field>
                {sendToScouts && (
                    <Select<string>
                        items={targetOptions}
                        value={skillName}
                        onValueChange={(selection: string | null) => onSkillNameChange(selection ?? skillName)}
                        disabled={targetOptionsLoading}
                    >
                        <SelectTrigger
                            size="sm"
                            aria-label="Scout that receives the note"
                            data-attr="inbox-report-note-target"
                        >
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {targetOptions.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                )}
                <span className="flex-1" />
                <Button size="sm" onClick={onCancel} disabledReason={saving ? 'Saving' : undefined}>
                    Cancel
                </Button>
                <Button
                    size="sm"
                    variant="primary"
                    loading={saving}
                    disabledReason={text.trim() ? undefined : 'Write a note first'}
                    onClick={onSubmit}
                    data-attr="inbox-report-note-submit"
                >
                    Add note
                </Button>
            </div>
            {/* A disabled checkbox has no tooltip, so the reason is shown as text. */}
            {sendToScoutsDisabledReason && (
                <Text size="xs" variant="muted" render={<span />}>
                    {sendToScoutsDisabledReason}
                </Text>
            )}
            {sendToScouts && (
                <Text size="xs" variant="muted" render={<span />}>
                    Scouts read the note at the start of every run until you retire it.
                </Text>
            )}
        </div>
    )
}
