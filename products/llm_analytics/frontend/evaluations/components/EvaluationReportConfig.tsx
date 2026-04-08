import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonDialog, LemonInput, LemonSelect, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'

import { evaluationReportLogic } from '../evaluationReportLogic'
import type { EvaluationReportDeliveryTarget, EvaluationReportFrequency } from '../types'

const GUIDANCE_PLACEHOLDER =
    "Optional guidance for the report agent. e.g. 'Focus on cost regressions across models', 'Compare latency between gpt-4o-mini and claude-sonnet', 'Keep it to 2 sections max'"

const FREQUENCY_OPTIONS = [
    { value: 'hourly' as const, label: 'Hourly' },
    { value: 'daily' as const, label: 'Daily' },
    { value: 'weekly' as const, label: 'Weekly' },
]

/** Shared delivery targets configuration */
function DeliveryTargetsConfig({
    emailValue,
    onEmailChange,
    slackIntegrationId,
    onSlackIntegrationChange,
    slackChannelValue,
    onSlackChannelChange,
}: {
    emailValue: string
    onEmailChange: (value: string) => void
    slackIntegrationId: number | null
    onSlackIntegrationChange: (value: number | null) => void
    slackChannelValue: string
    onSlackChannelChange: (value: string) => void
}): JSX.Element {
    const { slackIntegrations, integrations } = useValues(integrationsLogic)

    return (
        <>
            <div>
                <label className="font-semibold text-sm">Email recipients</label>
                <LemonInput
                    value={emailValue}
                    onChange={onEmailChange}
                    placeholder="email1@example.com, email2@example.com"
                    fullWidth
                />
                <p className="text-xs text-muted mt-1">Comma-separated email addresses</p>
            </div>
            <div>
                <label className="font-semibold text-sm">Slack channel</label>
                {!slackIntegrations?.length ? (
                    <SlackNotConfiguredBanner />
                ) : (
                    <div className="space-y-2">
                        <IntegrationChoice
                            integration="slack"
                            value={slackIntegrationId ?? undefined}
                            onChange={(newValue) => {
                                if (newValue !== slackIntegrationId) {
                                    onSlackChannelChange('')
                                }
                                onSlackIntegrationChange(newValue)
                            }}
                        />
                        {slackIntegrationId && (
                            <SlackChannelPicker
                                value={slackChannelValue}
                                onChange={(val) => onSlackChannelChange(val || '')}
                                integration={integrations!.find((i) => i.id === slackIntegrationId)!}
                            />
                        )}
                    </div>
                )}
            </div>
        </>
    )
}

/** Inline config shown during new evaluation creation */
function PendingReportConfig({ evaluationId }: { evaluationId: string }): JSX.Element {
    const { pendingConfig } = useValues(evaluationReportLogic({ evaluationId }))
    const {
        setPendingEnabled,
        setPendingFrequency,
        setPendingEmailValue,
        setPendingSlackIntegrationId,
        setPendingSlackChannelValue,
        setPendingReportPromptGuidance,
    } = useActions(evaluationReportLogic({ evaluationId }))

    return (
        <div className="bg-bg-light border rounded p-6">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h3 className="text-lg font-semibold mb-1">Scheduled reports</h3>
                    <p className="text-muted text-sm">
                        Get periodic AI-generated analysis of evaluation results delivered via email or Slack.
                    </p>
                </div>
                <LemonSwitch
                    checked={pendingConfig.enabled}
                    onChange={setPendingEnabled}
                    bordered
                    label={pendingConfig.enabled ? 'Enabled' : 'Disabled'}
                />
            </div>

            {pendingConfig.enabled && (
                <div className="space-y-4 mt-4">
                    <div>
                        <label className="font-semibold text-sm">Frequency</label>
                        <LemonSelect
                            value={pendingConfig.frequency}
                            onChange={(val) => val && setPendingFrequency(val)}
                            options={FREQUENCY_OPTIONS}
                            fullWidth
                        />
                    </div>
                    <DeliveryTargetsConfig
                        emailValue={pendingConfig.emailValue}
                        onEmailChange={setPendingEmailValue}
                        slackIntegrationId={pendingConfig.slackIntegrationId}
                        onSlackIntegrationChange={setPendingSlackIntegrationId}
                        slackChannelValue={pendingConfig.slackChannelValue}
                        onSlackChannelChange={setPendingSlackChannelValue}
                    />
                    <div>
                        <label className="font-semibold text-sm">Report agent guidance (optional)</label>
                        <LemonTextArea
                            value={pendingConfig.reportPromptGuidance}
                            onChange={setPendingReportPromptGuidance}
                            placeholder={GUIDANCE_PLACEHOLDER}
                            rows={3}
                        />
                        <p className="text-xs text-muted mt-1">
                            Steers the agent's focus, section choices, or scope. Appended to the base prompt.
                        </p>
                    </div>
                </div>
            )}
        </div>
    )
}

/** Toggle-based report management for existing evaluations */
function ExistingReportConfig({ evaluationId }: { evaluationId: string }): JSX.Element {
    const logic = evaluationReportLogic({ evaluationId })
    const { activeReport, reportsLoading } = useValues(logic)
    const { updateReport, deleteReport, createReport } = useActions(logic)

    // Local state: toggle controls form visibility, Save button creates the report
    const [formEnabled, setFormEnabled] = useState(false)
    const [frequency, setFrequency] = useState<EvaluationReportFrequency>('daily')
    const [emailValue, setEmailValue] = useState('')
    const [slackIntegrationId, setSlackIntegrationId] = useState<number | null>(null)
    const [slackChannelValue, setSlackChannelValue] = useState('')
    const [guidance, setGuidance] = useState('')

    // Seed the delivery-target form state from the active report so the user can edit
    // email/Slack targets without having to disable + recreate the schedule.
    useEffect(() => {
        if (!activeReport) {
            return
        }
        const emailTarget = activeReport.delivery_targets.find((t) => t.type === 'email')
        const slackTarget = activeReport.delivery_targets.find((t) => t.type === 'slack')
        setEmailValue(emailTarget?.value ?? '')
        setSlackIntegrationId(slackTarget?.integration_id ?? null)
        setSlackChannelValue(slackTarget?.channel ?? '')
        setGuidance(activeReport.report_prompt_guidance ?? '')
    }, [activeReport])

    const isEnabled = !!activeReport || formEnabled

    const handleToggle = (checked: boolean): void => {
        if (checked) {
            setFormEnabled(true)
        } else if (activeReport) {
            LemonDialog.open({
                title: 'Disable scheduled reports?',
                description: 'This will stop all future report deliveries. Past reports will be preserved.',
                primaryButton: {
                    children: 'Disable',
                    status: 'danger',
                    onClick: () => deleteReport(activeReport.id),
                },
                secondaryButton: { children: 'Cancel' },
            })
        } else {
            setFormEnabled(false)
        }
    }

    const hasEmail = emailValue.trim().length > 0
    const hasSlack = slackIntegrationId !== null && slackChannelValue.length > 0

    const handleSave = (): void => {
        const targets: EvaluationReportDeliveryTarget[] = []
        if (hasEmail) {
            targets.push({ type: 'email', value: emailValue.trim() })
        }
        if (hasSlack) {
            targets.push({ type: 'slack', integration_id: slackIntegrationId!, channel: slackChannelValue })
        }
        createReport({
            evaluationId,
            frequency,
            delivery_targets: targets,
            report_prompt_guidance: guidance,
        })
        setFormEnabled(false)
    }

    return (
        <div className="bg-bg-light border rounded p-6">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h3 className="text-lg font-semibold mb-1">Scheduled reports</h3>
                    <p className="text-muted text-sm">
                        Get periodic AI-generated analysis of evaluation results delivered via email or Slack.
                    </p>
                </div>
                <LemonSwitch
                    checked={isEnabled}
                    onChange={handleToggle}
                    bordered
                    loading={reportsLoading}
                    label={isEnabled ? 'Enabled' : 'Disabled'}
                />
            </div>

            {activeReport ? (
                <div className="space-y-4 mt-4">
                    <div>
                        <label className="font-semibold text-sm">Frequency</label>
                        <LemonSelect
                            value={activeReport.frequency}
                            onChange={(val) =>
                                val && updateReport({ reportId: activeReport.id, data: { frequency: val } })
                            }
                            options={FREQUENCY_OPTIONS}
                            fullWidth
                        />
                    </div>

                    <DeliveryTargetsConfig
                        emailValue={emailValue}
                        onEmailChange={setEmailValue}
                        slackIntegrationId={slackIntegrationId}
                        onSlackIntegrationChange={setSlackIntegrationId}
                        slackChannelValue={slackChannelValue}
                        onSlackChannelChange={setSlackChannelValue}
                    />

                    <div>
                        <label className="font-semibold text-sm">Report agent guidance (optional)</label>
                        <LemonTextArea
                            value={guidance}
                            onChange={setGuidance}
                            placeholder={GUIDANCE_PLACEHOLDER}
                            rows={3}
                        />
                        <p className="text-xs text-muted mt-1">
                            Steers the agent's focus, section choices, or scope. Appended to the base prompt.
                        </p>
                    </div>

                    {(() => {
                        const currentEmail = activeReport.delivery_targets.find((t) => t.type === 'email')?.value ?? ''
                        const currentSlack = activeReport.delivery_targets.find((t) => t.type === 'slack')
                        const currentSlackIntegrationId: number | null = currentSlack?.integration_id ?? null
                        const currentSlackChannel = currentSlack?.channel ?? ''
                        const currentGuidance = activeReport.report_prompt_guidance ?? ''
                        const targetsDirty =
                            emailValue.trim() !== currentEmail ||
                            slackIntegrationId !== currentSlackIntegrationId ||
                            slackChannelValue !== currentSlackChannel
                        const guidanceDirty = guidance !== currentGuidance
                        const isDirty = targetsDirty || guidanceDirty
                        const hasAnyTarget = hasEmail || hasSlack
                        return (
                            <div className="flex justify-end">
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    loading={reportsLoading}
                                    disabledReason={
                                        !isDirty
                                            ? 'No changes to save'
                                            : !hasAnyTarget
                                              ? 'Add at least one delivery target'
                                              : undefined
                                    }
                                    onClick={() => {
                                        const targets: EvaluationReportDeliveryTarget[] = []
                                        if (hasEmail) {
                                            targets.push({ type: 'email', value: emailValue.trim() })
                                        }
                                        if (hasSlack) {
                                            targets.push({
                                                type: 'slack',
                                                integration_id: slackIntegrationId!,
                                                channel: slackChannelValue,
                                            })
                                        }
                                        updateReport({
                                            reportId: activeReport.id,
                                            data: {
                                                delivery_targets: targets,
                                                report_prompt_guidance: guidance,
                                            },
                                        })
                                    }}
                                >
                                    Save changes
                                </LemonButton>
                            </div>
                        )
                    })()}

                    {activeReport.next_delivery_date && (
                        <div className="text-sm text-muted">
                            Next delivery: {new Date(activeReport.next_delivery_date).toLocaleString()}
                        </div>
                    )}

                    <p className="text-xs text-muted m-0">Generated reports appear in the Reports tab.</p>
                </div>
            ) : (
                formEnabled && (
                    <div className="space-y-4 mt-4">
                        <div>
                            <label className="font-semibold text-sm">Frequency</label>
                            <LemonSelect
                                value={frequency}
                                onChange={(val) => val && setFrequency(val)}
                                options={FREQUENCY_OPTIONS}
                                fullWidth
                            />
                        </div>
                        <DeliveryTargetsConfig
                            emailValue={emailValue}
                            onEmailChange={setEmailValue}
                            slackIntegrationId={slackIntegrationId}
                            onSlackIntegrationChange={setSlackIntegrationId}
                            slackChannelValue={slackChannelValue}
                            onSlackChannelChange={setSlackChannelValue}
                        />
                        <div>
                            <label className="font-semibold text-sm">Report agent guidance (optional)</label>
                            <LemonTextArea
                                value={guidance}
                                onChange={setGuidance}
                                placeholder={GUIDANCE_PLACEHOLDER}
                                rows={3}
                            />
                            <p className="text-xs text-muted mt-1">
                                Steers the agent's focus, section choices, or scope. Appended to the base prompt.
                            </p>
                        </div>
                        <div className="flex justify-end">
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={handleSave}
                                loading={reportsLoading}
                                disabledReason={!hasEmail && !hasSlack ? 'Add at least one delivery target' : undefined}
                            >
                                Save report schedule
                            </LemonButton>
                        </div>
                    </div>
                )
            )}
        </div>
    )
}

export function EvaluationReportConfig({ evaluationId }: { evaluationId: string }): JSX.Element {
    if (evaluationId === 'new') {
        return <PendingReportConfig evaluationId={evaluationId} />
    }
    return <ExistingReportConfig evaluationId={evaluationId} />
}
