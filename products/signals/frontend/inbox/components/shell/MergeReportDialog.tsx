import { useActions, useValues } from 'kea'

import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { MergeTargetCandidate, mergeTargetPickerLogic } from '../../logics/mergeTargetPickerLogic'
import { STATUS_LABELS } from '../badges/SignalReportStatusBadge'

// The merge API caps `reason` at 500 characters.
const MERGE_REASON_MAX_LENGTH = 500

export interface MergeReportDialogResult {
    survivor: MergeTargetCandidate
    reason: string
}

interface OpenMergeReportDialogParams {
    /** The report that is merged away. */
    reportId: string
    reportTitle?: string | null
    /** Called with the picked survivor and the reason once the user confirms. */
    onConfirm: (result: MergeReportDialogResult) => void | Promise<void>
}

/** Status, signal count and last update, so two reports with the same title can be told apart. */
function candidateDetail(candidate: MergeTargetCandidate): string {
    const signals = `${candidate.signalCount} ${candidate.signalCount === 1 ? 'signal' : 'signals'}`
    return [
        STATUS_LABELS[candidate.status] ?? candidate.status,
        signals,
        `updated ${dayjs(candidate.updatedAt).fromNow()}`,
    ].join(' · ')
}

function MergeTargetPicker({
    sourceReportId,
    value,
    onChange,
}: {
    sourceReportId: string
    value: MergeTargetCandidate | null
    onChange: (value: MergeTargetCandidate | null) => void
}): JSX.Element {
    const logic = mergeTargetPickerLogic({ sourceReportId })
    const { candidates, candidatesLoading } = useValues(logic)
    const { loadCandidates } = useActions(logic)

    // Rows from the previous search do not match the new input, and Enter picks the top row. Hide
    // them until the new results arrive, so Enter cannot pick a report the person did not search for.
    const results = candidatesLoading ? [] : candidates
    // A new search can drop the picked report from the results. Keep it in the options, so the
    // input still shows its title and not its id.
    const options = [...(value && !results.some((c) => c.id === value.id) ? [value] : []), ...results]

    return (
        // Enter in the picker picks a row, then bubbles to the LemonFormDialog, which submits on any
        // Enter while the form is valid. That submit reads the previous pick, so stop Enter here: a
        // merge into the wrong report cannot be undone.
        <div
            onKeyDown={(e) => {
                if (e.key === 'Enter') {
                    e.stopPropagation()
                }
            }}
        >
            <LemonInputSelect
                mode="single"
                value={value ? [value.id] : []}
                onChange={(keys) => onChange(options.find((c) => c.id === keys[0]) ?? null)}
                onInputChange={loadCandidates}
                options={options.map((c) => ({
                    key: c.id,
                    label: c.title,
                    labelComponent: (
                        <span className="flex min-w-0 items-baseline gap-2">
                            <span className="truncate">{c.title}</span>
                            <span className="shrink-0 text-xs text-secondary">{candidateDetail(c)}</span>
                        </span>
                    ),
                }))}
                loading={candidatesLoading}
                // The search runs on the server, which matches more than the visible title.
                disableFiltering
                placeholder="Search reports by title"
                emptyStateComponent={
                    <p className="m-0 p-2 text-secondary">
                        No open report matches. Only open reports can take a merge.
                    </p>
                }
                fullWidth
                autoFocus
                data-attr="inbox-merge-report-target"
            />
        </div>
    )
}

/**
 * Opens the merge dialog: pick the report that stays, plus an optional reason, then merge. The
 * caller wires `onConfirm` to the merge API, addressed by the survivor. Same shape as
 * {@link openResolveReportDialog}, so the verdict dialogs read alike.
 */
export function openMergeReportDialog({ reportId, reportTitle, onConfirm }: OpenMergeReportDialogParams): void {
    LemonDialog.openForm({
        title: `Merge "${reportTitle?.trim() ? reportTitle : 'Untitled report'}" into another report?`,
        description:
            "Pick the report that stays. This report's signals, work log and pull requests move to it, and this report moves to the archive. You can't undo a merge.",
        maxWidth: '36rem',
        overlayClassName: '!items-center',
        initialValues: { survivor: null as MergeTargetCandidate | null, reason: '' },
        content: (
            <div className="flex flex-col gap-3">
                <LemonField name="survivor" label="Merge into">
                    {({ value, onChange }) => (
                        <MergeTargetPicker sourceReportId={reportId} value={value} onChange={onChange} />
                    )}
                </LemonField>
                <LemonField
                    name="reason"
                    label="Reason"
                    info="Optional. Both reports show it, so a reader knows why they are the same issue."
                >
                    <LemonTextArea
                        // stopPropagation keeps Enter in this note from submitting the merge mid-sentence.
                        stopPropagation
                        placeholder="Why these reports describe the same issue."
                        maxLength={MERGE_REASON_MAX_LENGTH}
                        minRows={2}
                        maxRows={6}
                    />
                </LemonField>
            </div>
        ),
        errors: {
            survivor: (survivor) => (!survivor ? "You haven't picked a report" : undefined),
        },
        primaryButtonProps: { children: 'Merge report' },
        shouldAwaitSubmit: true,
        onSubmit: async ({ survivor, reason }) => {
            if (!survivor) {
                return
            }
            await onConfirm({ survivor, reason: (reason ?? '').trim() })
        },
    })
}
