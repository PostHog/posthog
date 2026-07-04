import { useActions, useValues } from 'kea'

import { IconPencil, IconPlusSmall, IconPulse, IconTrash } from '@posthog/icons'

import { NotFound } from 'lib/components/NotFound'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { BriefConfigModal } from './BriefConfigModal'
import type { ProductBriefListApi } from './generated/api.schemas'
import { ProductBriefStatusEnumApi } from './generated/api.schemas'
import { BRIEF_ALREADY_GENERATING_MESSAGE, BriefCitation, BriefSection, CITATION_TYPES, pulseLogic } from './pulseLogic'

export const scene: SceneExport = {
    component: PulseScene,
    logic: pulseLogic,
}

// Exhaustive over the enum so a new backend status fails compilation here instead of rendering unstyled.
const STATUS_TAG_TYPES: Record<ProductBriefStatusEnumApi, LemonTagType> = {
    [ProductBriefStatusEnumApi.Generating]: 'warning',
    [ProductBriefStatusEnumApi.Ready]: 'success',
    [ProductBriefStatusEnumApi.Quiet]: 'default',
    [ProductBriefStatusEnumApi.Failed]: 'danger',
}

export function PulseScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PULSE')
    const { aiConsentRequired, briefConfigs, selectedConfigId } = useValues(pulseLogic)
    const { selectConfig, openConfigModal } = useActions(pulseLogic)

    if (!isEnabled) {
        return <NotFound object="Pulse" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Pulse"
                description="Recurring product briefs: what happened, why it happened, and what to build next."
                resourceType={{ type: 'default_icon_type', forceIcon: <IconPulse /> }}
                actions={
                    <>
                        <LemonButton type="secondary" icon={<IconPlusSmall />} onClick={() => openConfigModal(null)}>
                            New config
                        </LemonButton>
                        <RunBriefButton />
                    </>
                }
            />

            {aiConsentRequired && (
                <LemonBanner type="warning">
                    Pulse runs AI over your project data, and your organization has not approved AI data processing yet.
                    Approve it in{' '}
                    <Link to={urls.settings('organization-details', 'organization-ai-consent')}>
                        organization settings
                    </Link>{' '}
                    to generate briefs.
                </LemonBanner>
            )}

            {briefConfigs.length > 0 && (
                <div className="flex items-center gap-2">
                    <span className="text-muted">Focus</span>
                    <LemonSelect<string | null>
                        size="small"
                        value={selectedConfigId}
                        onChange={(value) => selectConfig(value)}
                        options={[
                            { value: null, label: 'Whole project' },
                            ...briefConfigs.map((config) => ({ value: config.id, label: config.name })),
                        ]}
                    />
                    {selectedConfigId !== null && <SelectedConfigActions selectedConfigId={selectedConfigId} />}
                </div>
            )}

            <BriefsView />
            <BriefConfigModal />
        </SceneContent>
    )
}

function RunBriefButton(): JSX.Element {
    const { isGeneratingForSelectedConfig, generatedBriefLoading, selectedConfigId, aiConsentRequired } =
        useValues(pulseLogic)
    const { generateBrief } = useActions(pulseLogic)

    const disabledReason = aiConsentRequired
        ? 'Approve AI data processing first'
        : isGeneratingForSelectedConfig && !generatedBriefLoading
          ? BRIEF_ALREADY_GENERATING_MESSAGE
          : undefined

    return (
        <LemonButton
            type="primary"
            loading={generatedBriefLoading}
            disabledReason={disabledReason}
            onClick={() => generateBrief({ configId: selectedConfigId })}
        >
            Run brief now
        </LemonButton>
    )
}

function SelectedConfigActions({ selectedConfigId }: { selectedConfigId: string }): JSX.Element | null {
    const { briefConfigs, configIdBeingDeleted } = useValues(pulseLogic)
    const { openConfigModal, deleteConfig } = useActions(pulseLogic)

    const selectedConfig = briefConfigs.find((config) => config.id === selectedConfigId)
    if (!selectedConfig) {
        return null
    }
    const isDeleting = configIdBeingDeleted === selectedConfig.id

    return (
        <>
            <LemonButton
                size="small"
                icon={<IconPencil />}
                tooltip="Edit config"
                onClick={() => openConfigModal(selectedConfig)}
            />
            <LemonButton
                size="small"
                status="danger"
                icon={<IconTrash />}
                tooltip="Delete config"
                loading={isDeleting}
                disabledReason={isDeleting ? 'Deleting…' : undefined}
                onClick={() =>
                    LemonDialog.open({
                        title: `Delete "${selectedConfig.name}"?`,
                        description: 'Briefs already generated for this config are kept.',
                        primaryButton: {
                            children: 'Delete',
                            status: 'danger',
                            onClick: () => deleteConfig(selectedConfig.id),
                        },
                        secondaryButton: { children: 'Cancel' },
                    })
                }
            />
        </>
    )
}

function BriefsView(): JSX.Element {
    const { visibleBriefs, briefsLoading } = useValues(pulseLogic)

    if (briefsLoading && visibleBriefs.length === 0) {
        return (
            <div className="flex justify-center py-16">
                <Spinner className="text-2xl" />
            </div>
        )
    }

    if (visibleBriefs.length === 0) {
        return (
            <ProductIntroduction
                productName="Pulse"
                thingName="brief"
                titleOverride="No briefs yet"
                description="Run your first brief to see what happened in your product, why it happened, and what to build next."
                isEmpty
                actionElementOverride={<RunBriefButton />}
            />
        )
    }

    return (
        <div className="flex gap-4 items-start">
            <BriefHistoryList briefs={visibleBriefs} />
            <div className="flex-1 min-w-0">
                <BriefDetail />
            </div>
        </div>
    )
}

function BriefHistoryList({ briefs }: { briefs: ProductBriefListApi[] }): JSX.Element {
    const { selectedBriefId } = useValues(pulseLogic)
    const { selectBrief } = useActions(pulseLogic)

    return (
        <div className="w-72 shrink-0 flex flex-col gap-1">
            {briefs.map((brief) => (
                <LemonButton
                    key={brief.id}
                    fullWidth
                    active={brief.id === selectedBriefId}
                    onClick={() => selectBrief(brief.id)}
                >
                    <div className="flex items-center justify-between gap-2 w-full">
                        <TZLabel time={brief.created_at} />
                        <LemonTag type={STATUS_TAG_TYPES[brief.status]}>{brief.status}</LemonTag>
                    </div>
                </LemonButton>
            ))}
        </div>
    )
}

function BriefDetail(): JSX.Element | null {
    const { briefDetail, briefDetailLoading, briefDetailSections, selectedBriefId } = useValues(pulseLogic)

    if (!briefDetail || briefDetail.id !== selectedBriefId) {
        return briefDetailLoading ? <Spinner /> : null
    }

    if (briefDetail.status === ProductBriefStatusEnumApi.Generating) {
        return (
            <div className="flex items-center gap-2 border rounded p-8 justify-center">
                <Spinner />
                <span>Generating your brief…</span>
            </div>
        )
    }

    if (briefDetail.status === ProductBriefStatusEnumApi.Failed) {
        return <LemonBanner type="error">{briefDetail.error || 'Brief generation failed.'}</LemonBanner>
    }

    if (briefDetail.status === ProductBriefStatusEnumApi.Quiet) {
        return (
            <div className="border rounded p-8 text-center text-muted">Quiet period — nothing confident to report</div>
        )
    }

    return (
        <div className="flex flex-col gap-6">
            {briefDetailSections.map((section, index) => (
                <BriefSectionCard key={`${section.kind}-${index}`} section={section} />
            ))}
        </div>
    )
}

function BriefSectionCard({ section }: { section: BriefSection }): JSX.Element {
    return (
        <div className="border rounded p-4 flex flex-col gap-2">
            <h3 className="mb-0">{section.title}</h3>
            {/* LLM-generated markdown must not auto-load arbitrary image URLs (tracking-pixel / IP-leak vector). */}
            <LemonMarkdown disableImages>{section.markdown}</LemonMarkdown>
            {section.citations.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    {section.citations.map((citation) => (
                        <CitationTag key={`${citation.type}:${citation.ref}`} citation={citation} />
                    ))}
                </div>
            )}
        </div>
    )
}

function CitationTag({ citation }: { citation: BriefCitation }): JSX.Element {
    const { type, ref } = citation
    const citationType = ref ? CITATION_TYPES[type] : undefined
    const url = citationType?.url(ref)

    if (citationType && url) {
        return (
            <Link to={url}>
                <LemonTag>
                    {citationType.label} {ref}
                </LemonTag>
            </Link>
        )
    }
    return <LemonTag>{type ? `${type}:${ref}` : ref}</LemonTag>
}
