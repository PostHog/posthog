import './CreatePrModal.scss'

import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDivider, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'

import { createPrModalLogic } from './createPrModalLogic'

export interface CreatePrModalProps {
    isOpen: boolean
    /** Feature flag key the fix experiment ships behind */
    flagKey: string
    /** Success-criteria summary shown on the monitoring row */
    monitoringCriteria?: string
    onClose: () => void
    onConfirm: () => void
}

function AdvancedField({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <label className="flex flex-col gap-1 text-xs text-secondary">
            {label}
            {children}
        </label>
    )
}

/**
 * Demo "Create the fix PR" modal, shared by the inbox, focus mode, and report
 * surfaces. Confirming never creates anything: the caller decides what the demo
 * does next.
 */
export function CreatePrModal({
    isOpen,
    flagKey,
    monitoringCriteria = 'errors back to baseline, no new tickets',
    onClose,
    onConfirm,
}: CreatePrModalProps): JSX.Element {
    const { model, effort, rolloutStart, haltThreshold, monitoringDays } = useValues(createPrModalLogic)
    const { confirm, setModel, setEffort, setRolloutStart, setHaltThreshold, setMonitoringDays } =
        useActions(createPrModalLogic)

    // Both confirm paths run through here so the toast fires once, from the button and from Enter alike
    const handleConfirm = (): void => {
        confirm()
        onConfirm()
    }

    useKeyboardHotkeys(
        {
            enter: {
                // Enter confirms from the modal at large, but a focused button or menu item keeps its own Enter,
                // so tabbing to Cancel still cancels and a select's options still pick
                action: (event) => {
                    if (event.metaKey || event.ctrlKey || event.altKey) {
                        return
                    }
                    if ((event.target as HTMLElement | null)?.closest('a, button')) {
                        return
                    }
                    event.preventDefault()
                    handleConfirm()
                },
                disabled: !isOpen,
                willHandleEvent: true,
            },
        },
        [isOpen, onConfirm, confirm]
    )

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={860}
            overlayClassName="CreatePrModal__overlay"
            title="Create the fix PR"
            description="PostHog AI's coding agent writes the code, runs the test suite, reviews the change, and opens a pull request."
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose} data-attr="v2-create-pr-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleConfirm}
                        sideIcon={<KeyboardShortcut enter />}
                        data-attr="v2-create-pr-confirm"
                    >
                        Create PR
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4 md:flex-row">
                <div className="flex flex-1 flex-col gap-4">
                    <LemonBanner type="info" hideIcon>
                        <span className="text-xs font-normal">
                            Billed to your workspace when the PR opens. Cost depends on the model and effort level
                            selected.
                        </span>
                    </LemonBanner>
                    <div className="flex flex-col gap-2 rounded border border-primary p-3">
                        <div className="flex items-center gap-2">
                            <span className="text-[10px] font-semibold tracking-wide text-secondary uppercase">
                                Experiment created with the PR
                            </span>
                            <span className="flex-1" />
                            <span className="font-mono text-xs text-accent">{flagKey}</span>
                        </div>
                        <div className="flex items-baseline gap-2 text-xs">
                            <span className="w-24 flex-none text-tertiary">Rollout</span>
                            <span className="font-mono">{rolloutStart}% → 50% → 100%</span>
                            <span className="text-tertiary">over 3 days</span>
                        </div>
                        <div className="flex items-baseline gap-2 text-xs">
                            <span className="w-24 flex-none text-tertiary">Auto-halt</span>
                            <span>error rate &gt; {haltThreshold}× baseline reverts the flag in 60s</span>
                        </div>
                        <div className="flex items-baseline gap-2 text-xs">
                            <span className="w-24 flex-none text-tertiary">Monitoring</span>
                            <span>
                                {monitoringDays} days · {monitoringCriteria}
                            </span>
                        </div>
                    </div>
                </div>
                <div className="flex w-full flex-none flex-col gap-3 rounded bg-surface-secondary p-4 md:w-64">
                    <span className="text-[10px] font-semibold tracking-wide text-secondary uppercase">Advanced</span>
                    <AdvancedField label="Model">
                        <LemonSelect
                            value={model}
                            onChange={setModel}
                            options={['Opus 4.5', 'Sonnet 4.5', 'Haiku 4.5'].map((value) => ({ value, label: value }))}
                            size="small"
                            fullWidth
                            data-attr="v2-create-pr-model"
                        />
                    </AdvancedField>
                    <AdvancedField label="Effort level">
                        <LemonSelect
                            value={effort}
                            onChange={setEffort}
                            options={['low', 'medium', 'high', 'extra-high', 'max'].map((value) => ({
                                value,
                                label: value,
                            }))}
                            size="small"
                            fullWidth
                            data-attr="v2-create-pr-effort"
                        />
                    </AdvancedField>
                    <LemonDivider className="my-0" />
                    <AdvancedField label="Initial rollout %">
                        <LemonInput
                            type="number"
                            value={rolloutStart}
                            onChange={(value) => setRolloutStart(value ?? 10)}
                            min={1}
                            max={100}
                            size="small"
                        />
                    </AdvancedField>
                    <AdvancedField label="Auto-halt threshold (× baseline error rate)">
                        <LemonInput
                            type="number"
                            value={haltThreshold}
                            onChange={(value) => setHaltThreshold(value ?? 2)}
                            min={1}
                            size="small"
                        />
                    </AdvancedField>
                    <AdvancedField label="Monitoring window (days)">
                        <LemonInput
                            type="number"
                            value={monitoringDays}
                            onChange={(value) => setMonitoringDays(value ?? 7)}
                            min={1}
                            size="small"
                        />
                    </AdvancedField>
                </div>
            </div>
        </LemonModal>
    )
}
