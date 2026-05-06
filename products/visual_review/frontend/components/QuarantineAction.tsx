import { useState } from 'react'

import { LemonButton, LemonCheckbox, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

const SUGGESTED_REASONS = [
    'Non-deterministic rendering (animations, timestamps)',
    'Font hinting varies across environments',
    'Async content loading race condition',
    'Known flaky — fix in progress',
]

const DEFAULT_EXPIRY_DAYS = 30

/**
 * Identifiers carry an optional `--light` / `--dark` theme suffix.
 * When the user quarantines one variant, they almost always want
 * the sibling quarantined too — same code path, same flake.
 */
export function getThemeSibling(identifier: string): string | null {
    const parts = identifier.split('--')
    const themeIndex = [...parts].reverse().findIndex((part) => part === 'dark' || part === 'light')
    if (themeIndex === -1) {
        return null
    }
    const actualIndex = parts.length - 1 - themeIndex
    const siblingParts = [...parts]
    siblingParts[actualIndex] = siblingParts[actualIndex] === 'dark' ? 'light' : 'dark'
    return siblingParts.join('--')
}

interface QuarantineActionProps {
    identifier: string
    onQuarantine: (reason: string, identifiers: string[], expiresAt: string | null) => void
    /** Override the trigger button label. Defaults to "Quarantine this identifier". */
    triggerLabel?: string
}

/**
 * Quarantine modal + trigger button. Used from the run scene (per snapshot
 * sidebar) and the snapshot history scene (per identifier banner). Local
 * state for the modal — the parent owns the API call via `onQuarantine`.
 */
export function QuarantineAction({ identifier, onQuarantine, triggerLabel }: QuarantineActionProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const [reason, setReason] = useState('')
    const [includeSibling, setIncludeSibling] = useState(true)
    const [expiresAt, setExpiresAt] = useState<dayjs.Dayjs | null>(dayjs().add(DEFAULT_EXPIRY_DAYS, 'day'))

    const sibling = getThemeSibling(identifier)

    const handleSubmit = (): void => {
        const identifiers = [identifier]
        if (sibling && includeSibling) {
            identifiers.push(sibling)
        }
        onQuarantine(reason, identifiers, expiresAt ? expiresAt.toISOString() : null)
        setIsOpen(false)
        setReason('')
        setExpiresAt(dayjs().add(DEFAULT_EXPIRY_DAYS, 'day'))
    }

    return (
        <div>
            <LemonButton
                type="secondary"
                size="small"
                onClick={() => setIsOpen(true)}
                data-attr="visual-review-quarantine-open"
            >
                {triggerLabel ?? 'Quarantine this identifier'}
            </LemonButton>
            <LemonModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="Quarantine snapshot"
                footer={
                    <>
                        <LemonButton
                            type="secondary"
                            onClick={() => setIsOpen(false)}
                            data-attr="visual-review-quarantine-cancel"
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason={!reason.trim() ? 'Reason is required' : undefined}
                            onClick={handleSubmit}
                            data-attr="visual-review-quarantine-confirm"
                        >
                            Quarantine
                        </LemonButton>
                    </>
                }
            >
                <div className="space-y-4">
                    <p className="text-sm text-muted">
                        Quarantined identifiers appear as quarantined immediately and are excluded from gating when
                        future runs finalize — including pending runs on other branches. Snapshots are still captured
                        and diffed, just not gated on.
                    </p>

                    <div>
                        <label className="text-sm font-medium mb-1 block">Identifier</label>
                        <div className="font-mono text-xs text-muted bg-bg-3000 rounded px-2 py-1.5">{identifier}</div>
                        {sibling && (
                            <LemonCheckbox
                                className="mt-1.5"
                                label={
                                    <span className="text-xs">
                                        Also quarantine <span className="font-mono">{sibling}</span>
                                    </span>
                                }
                                checked={includeSibling}
                                onChange={setIncludeSibling}
                            />
                        )}
                    </div>

                    <div>
                        <label className="text-sm font-medium mb-1 block">Reason</label>
                        <LemonInput
                            placeholder="Why is this snapshot quarantined?"
                            value={reason}
                            onChange={setReason}
                            autoFocus
                        />
                        <div className="flex flex-wrap gap-1 mt-1.5">
                            {SUGGESTED_REASONS.map((suggestion) => (
                                <button
                                    key={suggestion}
                                    type="button"
                                    className="text-[11px] text-muted hover:text-default bg-bg-3000 hover:bg-border rounded px-1.5 py-0.5 transition-colors"
                                    onClick={() => setReason(suggestion)}
                                >
                                    {suggestion}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div>
                        <label className="text-sm font-medium mb-1 block">Expires</label>
                        <LemonCalendarSelectInput
                            value={expiresAt}
                            onChange={setExpiresAt}
                            placeholder="No expiry"
                            clearable
                        />
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}
