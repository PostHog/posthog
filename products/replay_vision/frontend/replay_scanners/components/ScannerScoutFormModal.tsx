import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { SignalScoutOutputDestinationsApi } from 'products/signals/frontend/generated/api.schemas'
import { prettifyScoutSkillName } from 'products/signals/frontend/inbox/utils/scoutRunsWindow'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import { scannerScoutTemplate, scoutBodyPlaceholders } from '../scannerScout'
import { SCOUT_REPORT_EMITTED_EVENT, webhookUrlError } from '../scannerScoutDelivery'
import type { ScannerScoutForm } from '../scannerScoutLogic'
import { scannerScoutLogic } from '../scannerScoutLogic'
import { parseScoutCadence, SCOUT_FREQUENCY_OPTIONS, scoutCadenceToCron } from '../scoutCadence'
import { ScannerScoutSlackDestination } from './ScannerScoutSlackDestination'
import { ScoutInstructionsField } from './ScoutInstructionsField'

type ScoutFormTab = 'instructions' | 'schedule' | 'delivery'

function FieldRow({ label, hint, control }: { label: string; hint: string; control: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-4">
            <div className="flex min-w-0 flex-col">
                <span className="text-sm text-default">{label}</span>
                <span className="text-xs text-muted">{hint}</span>
            </div>
            {control}
        </div>
    )
}

function ScheduleFields({ cron, onChange }: { cron: string; onChange: (cron: string) => void }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const cadence = parseScoutCadence(cron)

    if (!cadence) {
        return (
            <span className="text-sm text-muted">
                This scout runs on a custom schedule set outside Vision (
                <span className="font-mono text-xs">{cron}</span>).
            </span>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <FieldRow
                label="Frequency"
                hint="How often the scout runs."
                control={
                    <LemonSelect
                        size="small"
                        value={cadence.frequency}
                        options={SCOUT_FREQUENCY_OPTIONS}
                        className="w-44"
                        onChange={(frequency) => onChange(scoutCadenceToCron({ ...cadence, frequency }))}
                        data-attr="vision-scout-form-frequency"
                    />
                }
            />
            <FieldRow
                label="Run time"
                hint={`Uses the project timezone (${currentTeam?.timezone ?? 'UTC'}).`}
                control={
                    <LemonInput
                        type="time"
                        step={60}
                        size="small"
                        value={cadence.time}
                        className="w-44"
                        onChange={(time) => time && onChange(scoutCadenceToCron({ ...cadence, time }))}
                        data-attr="vision-scout-form-time"
                    />
                }
            />
        </div>
    )
}

/**
 * The scout form, used both to create one from a template and to edit an existing one. Same tabs
 * either way, so delivery is set up at creation rather than only afterwards: the draft is local and
 * a single footer action commits it, since a half-filled scout should never be persisted.
 */
export function ScannerScoutFormModal({
    scannerId,
    scannerName,
}: {
    scannerId: string
    scannerName: string
}): JSX.Element | null {
    const logic = scannerScoutLogic({ scannerId, scannerName })
    const {
        createTemplateKey,
        settingsSkillName,
        scoutConfigsForScanner,
        skillPrompt,
        skillPromptLoading,
        scoutDelivery,
        scoutDeliveryLoading,
        creating,
        settingsSaving,
    } = useValues(logic)
    const { closeCreateModal, closeScoutSettings, createScout, saveScoutSettings } = useActions(logic)

    // The trend template is written for the one output this scanner emits, so it needs the type.
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    // Rebuilding the templates on every keystroke would regenerate three multi-KB prompts.
    const template = useMemo(
        () => (createTemplateKey ? scannerScoutTemplate(createTemplateKey, scannerId, scanner?.scanner_type) : null),
        [createTemplateKey, scannerId, scanner?.scanner_type]
    )
    const config = scoutConfigsForScanner.find((candidate) => candidate.skill_name === settingsSkillName)
    const [activeTab, setActiveTab] = useState<ScoutFormTab>('instructions')
    const [form, setForm] = useState<ScannerScoutForm>(() => ({
        name: template ? template.defaultName : config ? prettifyScoutSkillName(config.skill_name) : '',
        body: template ? template.body : '',
        cron: template ? template.cron : (config?.run_cron_schedule ?? ''),
        outputDestinations: (config?.output_destinations ?? {}) as SignalScoutOutputDestinationsApi,
        webhookUrl: '',
    }))

    // A settings form opens before its instructions and destinations have loaded, so the draft is
    // seeded once, when both have arrived for THIS scout. Both loaders keep their previous value on
    // failure, so seeding without checking whose they are would put one scout's settings into
    // another and save them there. The flag is what makes it once: keying on a field being empty
    // would refill whatever the user had just cleared.
    const loadedForThisScout =
        skillPrompt?.skillName === settingsSkillName && scoutDelivery?.skillName === settingsSkillName
    const [seeded, setSeeded] = useState(false)
    useEffect(() => {
        if (!template && !seeded && loadedForThisScout) {
            setSeeded(true)
            setForm((current) => ({
                ...current,
                body: skillPrompt?.body ?? '',
                webhookUrl: scoutDelivery?.webhook?.url ?? '',
            }))
        }
    }, [template, seeded, loadedForThisScout, skillPrompt, scoutDelivery])

    if (!template && !config) {
        return null
    }

    const patch = (updates: Partial<ScannerScoutForm>): void => setForm((current) => ({ ...current, ...updates }))
    const close = (): void => (template ? closeCreateModal() : closeScoutSettings())
    // Neither loader is retried, so a failure has to block the save: saving a draft seeded from
    // nothing would wipe the instructions this form never managed to show.
    const loadFailed = !template && !seeded && !skillPromptLoading && !scoutDeliveryLoading && !loadedForThisScout
    const stillLoading = !template && !seeded && !loadFailed
    const webhookError = form.webhookUrl.trim() ? webhookUrlError(form.webhookUrl.trim()) : null
    // The scratch template ships its judgment calls as ALL-CAPS slots; a scout saved with them
    // still in place would run against instructions nobody wrote.
    const placeholders = scoutBodyPlaceholders(form.body)
    const unchanged =
        !template &&
        !!config &&
        form.body === (skillPrompt?.body ?? '') &&
        form.cron === config.run_cron_schedule &&
        JSON.stringify(form.outputDestinations ?? {}) === JSON.stringify(config.output_destinations ?? {}) &&
        form.webhookUrl.trim() === (scoutDelivery?.webhook?.url ?? '')

    const submitDisabledReason = (): string | undefined => {
        const editDisabledReason = getReplayVisionEditDisabledReason(scanner?.user_access_level)
        if (editDisabledReason) {
            return editDisabledReason
        }
        if (loadFailed) {
            return "Couldn't load this scout's current settings"
        }
        if (stillLoading) {
            return 'Loading the scout'
        }
        if (!form.name.trim()) {
            return 'Give the scout a name'
        }
        if (!form.body.trim()) {
            return 'The instructions cannot be empty'
        }
        if (placeholders.length > 0) {
            return 'Replace or remove the placeholders in the instructions'
        }
        return webhookError ?? (unchanged ? 'No changes to save' : undefined)
    }

    return (
        <LemonModal
            isOpen
            onClose={close}
            title={template ? `New scout: ${template.title.toLowerCase()}` : `${form.name} settings`}
            description={
                template
                    ? `${template.description} Review it before creating the scout.`
                    : "Changes take effect on the scout's next run."
            }
            width={720}
            footer={
                <>
                    <LemonButton type="secondary" onClick={close} data-attr="vision-scout-form-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => (template ? createScout(form) : saveScoutSettings(form))}
                        loading={creating || settingsSaving}
                        disabledReason={submitDisabledReason()}
                        data-attr="vision-scout-form-submit"
                    >
                        {template ? 'Create scout' : 'Save changes'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-default">Name</span>
                    <LemonInput
                        value={form.name}
                        onChange={(name) => patch({ name })}
                        placeholder={template?.defaultName}
                        maxLength={45}
                        // A scout's name is its identity in the fleet, so renaming isn't possible
                        // without losing its run history.
                        disabledReason={template ? undefined : "A scout's name can't be changed after it's created"}
                        data-attr="vision-scout-form-name"
                    />
                </div>
                <LemonTabs
                    activeKey={activeTab}
                    onChange={setActiveTab}
                    data-attr="vision-scout-form-tabs"
                    tabs={[
                        {
                            key: 'instructions',
                            label: 'Instructions',
                            content: stillLoading ? (
                                <LemonSkeleton className="h-80 w-full rounded" />
                            ) : (
                                <div className="flex flex-col gap-2">
                                    <span className="text-xs text-muted">
                                        What the scout looks for and what counts as worth reporting. It reads the
                                        scanner's new observations on every run.
                                    </span>
                                    <ScoutInstructionsField
                                        value={form.body}
                                        onChange={(body) => patch({ body })}
                                        minRows={14}
                                        maxRows={20}
                                        dataAttr="vision-scout-form-instructions"
                                    />
                                    {placeholders.length > 0 && (
                                        <span className="text-[11.5px] text-danger">
                                            Replace or remove the highlighted placeholders to create this scout.
                                        </span>
                                    )}
                                </div>
                            ),
                        },
                        {
                            key: 'schedule',
                            label: 'Schedule',
                            content: <ScheduleFields cron={form.cron} onChange={(cron) => patch({ cron })} />,
                        },
                        {
                            key: 'delivery',
                            label: 'Delivery',
                            content: (
                                <div className="flex flex-col gap-4">
                                    <ScannerScoutSlackDestination
                                        destinations={form.outputDestinations}
                                        onChange={(outputDestinations) => patch({ outputDestinations })}
                                    />
                                    <div className="flex flex-col gap-2 border-t border-primary pt-3">
                                        <span className="text-xs text-default">Webhook</span>
                                        <LemonInput
                                            value={form.webhookUrl}
                                            onChange={(webhookUrl) => patch({ webhookUrl })}
                                            placeholder="https://example.com/hooks/replay-vision"
                                            disabled={stillLoading}
                                            status={webhookError ? 'danger' : undefined}
                                            className="max-w-md"
                                            data-attr="vision-scout-form-webhook"
                                        />
                                        {webhookError ? (
                                            <span className="text-[11.5px] text-danger">{webhookError}</span>
                                        ) : (
                                            <span className="text-[11.5px] text-muted">
                                                Leave empty for no webhook. Delivery runs through a destination in Data
                                                pipelines, where you can see each attempt.
                                            </span>
                                        )}
                                    </div>
                                    <div className="flex flex-col gap-1 border-t border-primary pt-3">
                                        <span className="text-xs text-default">Anywhere else</span>
                                        <span className="text-[11.5px] text-muted">
                                            Every digest is also captured in this project as a{' '}
                                            <code>{SCOUT_REPORT_EMITTED_EVENT}</code> event, carrying its title,
                                            summary, priority and a link. Build insights on it, or send it somewhere
                                            these options don't cover with a{' '}
                                            <Link to={urls.dataPipelinesNew('destination')}>
                                                destination in Data pipelines
                                            </Link>
                                            .
                                        </span>
                                    </div>
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
        </LemonModal>
    )
}
