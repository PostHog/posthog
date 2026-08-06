import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconInfo, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip/Tooltip'
import { compactNumber, humanizeBytes } from 'lib/utils/numbers'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { LogsSamplingForm } from 'products/logs/frontend/components/LogsSampling/LogsSamplingForm'
import { logsSamplingFormLogic } from 'products/logs/frontend/components/LogsSampling/logsSamplingFormLogic'
import { samplingFormSaveDisabledReason } from 'products/logs/frontend/components/LogsSampling/samplingFormSaveDisabledReason'
import { LogsSamplingRuleApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsSamplingDetailSceneLogicProps, logsSamplingDetailSceneLogic } from './logsSamplingDetailSceneLogic'

export const scene: SceneExport<LogsSamplingDetailSceneLogicProps> = {
    component: LogsSamplingDetailScene,
    logic: logsSamplingDetailSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function LogsSamplingDetailScene(): JSX.Element {
    const { rule, ruleLoading } = useValues(logsSamplingDetailSceneLogic)

    if (!rule && !ruleLoading) {
        return (
            <SceneContent>
                <div className="p-8 text-muted text-center">Drop rule not found.</div>
            </SceneContent>
        )
    }

    if (!rule) {
        return (
            <SceneContent>
                <div className="p-8 text-muted text-center">Loading…</div>
            </SceneContent>
        )
    }

    const formProps = { rule }

    return (
        <BindLogic logic={logsSamplingFormLogic} props={formProps}>
            <LogsSamplingDetailFormBody rule={rule} />
        </BindLogic>
    )
}

function LogsSamplingDetailFormBody({ rule }: { rule: LogsSamplingRuleApi }): JSX.Element {
    const formProps = { rule }
    const { deleteRule, loadRuleDropImpact24h } = useActions(logsSamplingDetailSceneLogic)
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic(formProps))
    const { samplingForm, isSamplingFormSubmitting } = useValues(logsSamplingFormLogic(formProps))
    const { ruleDropImpact24h, ruleDropImpact24hLoading } = useValues(logsSamplingDetailSceneLogic)
    const saveDisabledReason = samplingFormSaveDisabledReason(samplingForm)

    const confirmDelete = (): void => {
        LemonDialog.open({
            title: 'Delete drop rule?',
            description:
                'This cannot be undone. In-flight ingestion workers may briefly still use a cached copy of the rule.',
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteRule(),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <SceneContent>
            <Form logic={logsSamplingFormLogic} props={formProps} formKey="samplingForm" enableFormOnSubmit>
                <SceneTitleSection
                    name={samplingForm.name || rule.name}
                    resourceType={{ type: 'logs' }}
                    canEdit
                    onNameChange={(name) => setSamplingFormValue('name', name)}
                    renameDebounceMs={0}
                    actions={
                        <LemonButton type="secondary" status="danger" onClick={confirmDelete}>
                            Delete
                        </LemonButton>
                    }
                />
                <SceneStickyBar>
                    <div className="flex items-center justify-between gap-2">
                        <div className="text-secondary text-sm flex items-center gap-1.5">
                            {ruleDropImpact24h === null && !ruleDropImpact24hLoading ? (
                                <span className="text-muted" title="Drop impact for the last 24 hours is not available">
                                    —
                                </span>
                            ) : ruleDropImpact24h === null ? (
                                <span className="text-muted">Loading drop impact…</span>
                            ) : (
                                <>
                                    {/* Keep the last known number visible during a manual refresh so
                                        users can compare before / after rather than seeing it disappear.
                                        Bytes are reported alongside records once the per-row bytes_uncompressed
                                        signal lands on each row at ingest — older drops attribute 0 bytes and
                                        the byte clause is hidden. */}
                                    <span>
                                        ~{compactNumber(ruleDropImpact24h.records)} log lines
                                        {ruleDropImpact24h.bytes > 0 && (
                                            <> (~{humanizeBytes(ruleDropImpact24h.bytes)})</>
                                        )}{' '}
                                        dropped in the last 24 hours (ingestion).
                                    </span>
                                    <Tooltip
                                        title={
                                            <>
                                                From app metrics keyed by this rule. Service-scoped rules only affect
                                                that service; others are counted across the project. Numbers can lag a
                                                minute or two — refresh after a short wait if you just enabled or edited
                                                the rule.
                                            </>
                                        }
                                    >
                                        <IconInfo className="text-muted-alt text-base shrink-0" />
                                    </Tooltip>
                                </>
                            )}
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                icon={<IconRefresh />}
                                onClick={() => loadRuleDropImpact24h(undefined)}
                                loading={ruleDropImpact24hLoading}
                                disabledReason={ruleDropImpact24hLoading ? 'Refreshing…' : undefined}
                                tooltip="Refresh drop impact (last 24h)"
                                aria-label="Refresh drop impact"
                            />
                        </div>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isSamplingFormSubmitting}
                            disabledReason={saveDisabledReason ?? undefined}
                        >
                            Save changes
                        </LemonButton>
                    </div>
                </SceneStickyBar>
                <div className="flex flex-col gap-6 p-4">
                    <LogsSamplingForm />
                </div>
            </Form>
        </SceneContent>
    )
}
