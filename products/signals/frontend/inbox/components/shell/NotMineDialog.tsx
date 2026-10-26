import { MemberSelect } from 'lib/components/MemberSelect'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { UserBasicType } from '~/types'

interface OpenNotMineDialogParams {
    reportTitle?: string | null
    /** Left out of the picker: handing a report to yourself would only remove you from it. */
    currentUser: Pick<UserBasicType, 'id' | 'uuid'> | null
    /** Called with the chosen teammate's uuid, or null to let the agent pick. */
    onConfirm: (replacementUuid: string | null) => void | Promise<void>
}

/**
 * Opens the Not mine dialog: the person stops being a reviewer and can name who should get the report.
 * Unlike {@link openDismissReportDialog}, the report stays open, so a routing mistake never hides the issue.
 */
export function openNotMineDialog({ reportTitle, currentUser, onConfirm }: OpenNotMineDialogParams): void {
    const primaryButtonProps = { children: 'Hand off', 'data-attr': 'inbox-not-mine-submit' }
    LemonDialog.openForm({
        title: `Hand off "${reportTitle?.trim() ? reportTitle : 'Untitled report'}"?`,
        description: "You'll stop being a reviewer on this report. The report stays open.",
        maxWidth: '32rem',
        overlayClassName: '!items-center',
        initialValues: { replacementUuid: null as string | null },
        content: (
            <LemonField
                name="replacementUuid"
                label="Who should get it instead?"
                info="Optional. If you leave this empty, the agent tries to pick someone else."
            >
                {({ value, onChange }) => (
                    <MemberSelect
                        type="secondary"
                        defaultLabel="Let the agent pick"
                        value={value}
                        // The picker compares exclusions by uuid while a uuid is selected and by id
                        // otherwise, so pass both forms of the current user.
                        excludedMembers={currentUser ? [currentUser.id, currentUser.uuid] : []}
                        onChange={(user) => onChange(user?.uuid ?? null)}
                    />
                )}
            </LemonField>
        ),
        errors: {},
        primaryButtonProps,
        shouldAwaitSubmit: true,
        onSubmit: async ({ replacementUuid }) => {
            await onConfirm(replacementUuid ?? null)
        },
    })
}
