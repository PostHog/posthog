import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonInputSelect, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import {
    QuarantineModalState,
    QuarantineSubmitInput,
    inferOwnerFromSelector,
} from '../scenes/engineeringAnalyticsLogic'

// Common flake categories (industry-standard buckets). 'Other' reveals a free-text field.
const REASON_OPTIONS = [
    'Concurrency / race condition',
    'Timing / timeout',
    'Nondeterministic ordering or data',
    'Test isolation / shared state',
    'Eventual consistency / async wait',
    'External dependency or network',
    'Resource / environment',
]
const OTHER_REASON = 'Other'

// Mirrors the backend cap (core.MAX_QUARANTINE_DAYS); the server rejects anything further out.
const MAX_QUARANTINE_DAYS = 30
const DEFAULT_QUARANTINE_DAYS = 14

interface QuarantineTestModalProps {
    /** Null closes the modal; non-null seeds it for a quarantine or an extend. */
    modal: QuarantineModalState | null
    /** Owning teams already present in the quarantine file; the dropdown also accepts a custom value. */
    ownerOptions: string[]
    submitting: boolean
    onClose: () => void
    onSubmit: (input: QuarantineSubmitInput) => void
}

export function QuarantineTestModal({
    modal,
    ownerOptions,
    submitting,
    onClose,
    onSubmit,
}: QuarantineTestModalProps): JSX.Element {
    const isExtend = modal?.action === 'extend'

    const [selector, setSelector] = useState('')
    // A picked category, or OTHER_REASON when the reason is free-text (held in customReason).
    const [reasonChoice, setReasonChoice] = useState('')
    const [customReason, setCustomReason] = useState('')
    const [owner, setOwner] = useState('')
    const [expires, setExpires] = useState<dayjs.Dayjs | null>(dayjs().add(DEFAULT_QUARANTINE_DAYS, 'day'))
    // 'Edit details' flips a confirm-presentation modal into the full form.
    const [editing, setEditing] = useState(false)

    // Reseed when a new modal opens; keyed on identity so background refreshes don't trample edits.
    useEffect(() => {
        if (!modal) {
            return
        }
        setSelector(modal.selector)
        // An existing reason that isn't one of the buckets falls into the 'Other' free-text path.
        const isKnown = REASON_OPTIONS.includes(modal.reason)
        setReasonChoice(modal.reason ? (isKnown ? modal.reason : OTHER_REASON) : '')
        setCustomReason(isKnown ? '' : modal.reason)
        // New quarantines suggest the owning team from a product selector; extend keeps the entry's owner.
        setOwner(modal.owner || (modal.action === 'extend' ? '' : inferOwnerFromSelector(modal.selector)))
        setExpires(dayjs().add(DEFAULT_QUARANTINE_DAYS, 'day'))
        setEditing(false)
    }, [modal])

    const isConfirm = !!modal?.confirm && !editing && !isExtend

    const reason = reasonChoice === OTHER_REASON ? customReason.trim() : reasonChoice
    // Backend requires a future expiry within the cap; mirror that so submit can't 400.
    const expiresValid = !!expires && expires.isAfter(dayjs(), 'day')

    const canSubmit = !!selector.trim() && !!reason && !!owner.trim() && expiresValid
    const disabledReason = !selector.trim()
        ? 'A test selector is required'
        : !reason
          ? 'A reason is required'
          : !owner.trim()
            ? 'An owning team is required'
            : !expiresValid
              ? 'Pick an expiry date in the future'
              : undefined

    const handleSubmit = (): void => {
        if (!canSubmit || !modal || !expires) {
            return
        }
        onSubmit({
            action: modal.action,
            selector: selector.trim(),
            reason,
            owner: owner.trim(),
            issue: modal.issue,
            expires: expires.format('YYYY-MM-DD'),
            // Mode isn't editable here: new quarantines run as xfail; extend keeps the entry's mode.
            mode: modal.mode,
        })
    }

    return (
        <LemonModal
            isOpen={!!modal}
            onClose={onClose}
            title={isExtend ? 'Extend quarantine' : 'Quarantine a flaky test'}
            description={
                isExtend
                    ? 'Re-stamps the expiry on an existing entry and opens a PR. It takes effect once the PR merges.'
                    : 'Opens a tracking issue and a PR that masks this test in CI until its expiry. It takes effect once the PR merges.'
            }
            footer={
                <>
                    {isConfirm && (
                        <LemonButton
                            type="tertiary"
                            onClick={() => setEditing(true)}
                            data-attr="eng-analytics-quarantine-edit"
                        >
                            Edit details
                        </LemonButton>
                    )}
                    <LemonButton type="secondary" onClick={onClose} data-attr="eng-analytics-quarantine-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={submitting}
                        disabledReason={submitting ? 'Opening PR…' : disabledReason}
                        onClick={handleSubmit}
                        data-attr="eng-analytics-quarantine-confirm"
                    >
                        {isExtend ? 'Extend and open PR' : 'Quarantine and open PR'}
                    </LemonButton>
                </>
            }
        >
            {isConfirm ? (
                // Glanceable confirmation for prefilled openers: everything is review-only except the
                // owner, the one field a leaderboard row can't always infer.
                <div className="flex flex-col gap-4">
                    <div>
                        <div className="mb-1 text-sm font-medium">Test selector</div>
                        <div className="rounded bg-surface-secondary px-2 py-1.5 font-mono text-xs break-all">
                            {selector}
                        </div>
                    </div>
                    <div>
                        <div className="mb-1 text-sm font-medium">Reason</div>
                        <div className="text-sm text-secondary">{reason}</div>
                    </div>
                    <div>
                        <div className="mb-1 text-sm font-medium">Expires</div>
                        <div className="text-sm">
                            {expires?.format('MMMM D, YYYY')}
                            <span className="ml-1 text-tertiary">
                                (in {DEFAULT_QUARANTINE_DAYS} days — the test gates CI again after this unless extended)
                            </span>
                        </div>
                    </div>
                    <div>
                        <label className="mb-1 block text-sm font-medium">Owner</label>
                        <LemonInputSelect
                            mode="single"
                            allowCustomValues
                            value={owner ? [owner] : []}
                            onChange={(values) => setOwner(values[0] ?? '')}
                            options={ownerOptions.map((option) => ({ key: option, label: option }))}
                            placeholder="Select the owning team"
                            data-attr="eng-analytics-quarantine-owner"
                        />
                    </div>
                </div>
            ) : (
                <div className="flex flex-col gap-4">
                    <div>
                        <label className="mb-1 block text-sm font-medium">Test selector</label>
                        {isExtend ? (
                            <div className="rounded bg-surface-secondary px-2 py-1.5 font-mono text-xs text-secondary">
                                {selector}
                            </div>
                        ) : (
                            <LemonInput
                                value={selector}
                                onChange={setSelector}
                                placeholder="posthog/path/test.py::TestClass::test_method or product:my-product"
                                autoFocus
                            />
                        )}
                    </div>

                    <div>
                        <label className="mb-1 block text-sm font-medium">Reason</label>
                        <LemonSelect
                            value={reasonChoice || null}
                            onChange={(value) => setReasonChoice(value ?? '')}
                            options={[
                                ...REASON_OPTIONS.map((option) => ({ value: option, label: option })),
                                { value: OTHER_REASON, label: 'Other…' },
                            ]}
                            placeholder="Select a reason"
                            fullWidth
                            data-attr="eng-analytics-quarantine-reason"
                        />
                        {reasonChoice === OTHER_REASON && (
                            <LemonInput
                                className="mt-2"
                                value={customReason}
                                onChange={setCustomReason}
                                placeholder="Describe the reason"
                                autoFocus
                            />
                        )}
                    </div>

                    <div>
                        <label className="mb-1 block text-sm font-medium">Owner</label>
                        <LemonInputSelect
                            mode="single"
                            allowCustomValues
                            value={owner ? [owner] : []}
                            onChange={(values) => setOwner(values[0] ?? '')}
                            options={ownerOptions.map((option) => ({ key: option, label: option }))}
                            placeholder="Select a team"
                            data-attr="eng-analytics-quarantine-owner"
                        />
                    </div>

                    <div>
                        <label className="mb-1 block text-sm font-medium">Expires</label>
                        <LemonCalendarSelectInput
                            value={expires}
                            onChange={setExpires}
                            placeholder="Pick an expiry"
                            clearable={false}
                            selectionPeriod="upcoming"
                        />
                        <div className="mt-1 text-xs text-tertiary">
                            At most {MAX_QUARANTINE_DAYS} days out. After this the test gates CI again unless extended.
                        </div>
                    </div>
                </div>
            )}
        </LemonModal>
    )
}
