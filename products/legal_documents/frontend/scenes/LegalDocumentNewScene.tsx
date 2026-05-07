import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconBalance, IconSend } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { LegalDocumentsPreview } from '../components/LegalDocumentsPreview'
import { FIELD_IDS } from './legalDocumentsConstants'
import { DPAMode, LegalDocumentType, legalDocumentsLogic } from './legalDocumentsLogic'

function buildDocumentTypeOptions(
    existingTypes: Set<LegalDocumentType>
): { value: LegalDocumentType; label: string; disabledReason?: string }[] {
    const alreadyExistsReason = (type: LegalDocumentType): string | undefined =>
        existingTypes.has(type)
            ? `Your organization already has a ${type}. Contact support if you need a new one.`
            : undefined
    return [
        {
            value: 'DPA',
            label: 'Data Processing Agreement (DPA)',
            disabledReason: alreadyExistsReason('DPA'),
        },
        {
            value: 'BAA',
            label: 'Business Associate Agreement (BAA)',
            disabledReason: alreadyExistsReason('BAA'),
        },
    ]
}

const DPA_MODE_OPTIONS: { value: DPAMode; label: string; description: string }[] = [
    {
        value: 'pretty',
        label: 'A perfectly legal doc, but with some pizazz',
        description: 'Holds up in a court of law, but with a nicer font and a color logo.',
    },
    {
        value: 'lawyer',
        label: 'Drab and dull — preferred by lawyers',
        description: 'Because lawyers hate fun but love Times New Roman.',
    },
    {
        value: 'fairytale',
        label: 'A fairy tale story',
        description: "Explain it to me like I'm five. Preview only — not legally binding, can't be submitted.",
    },
    {
        value: 'tswift',
        label: "Taylor Swift's version",
        description: 'Preview only — our lawyers refuse to recognize this as a binding document.',
    },
]

export const scene: SceneExport = {
    component: LegalDocumentNewScene,
    logic: legalDocumentsLogic,
}

export function LegalDocumentNewScene(): JSX.Element {
    const {
        legalDocument,
        legalDocumentHasErrors,
        isLegalDocumentSubmitting,
        hasQualifyingBaaAddon,
        isDpaModeSubmittable,
        existingDocumentOfCurrentType,
        existingDocumentTypes,
    } = useValues(legalDocumentsLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const { setDocumentType, setDpaMode } = useActions(legalDocumentsLogic)
    const isEnabled = useFeatureFlag('LEGAL_DOCUMENTS')

    if (!isCloudOrDev) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Legal documents"
                    resourceType={{ type: 'default_icon_type', forceIcon: <IconBalance /> }}
                    forceBackTo={{
                        key: Scene.LegalDocuments,
                        name: 'Legal documents',
                        path: urls.legalDocuments(),
                    }}
                />
                <LemonBanner type="info">
                    <p className="mb-0">Legal documents are only available on PostHog Cloud.</p>
                </LemonBanner>
            </SceneContent>
        )
    }

    if (!isEnabled) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Legal documents"
                    resourceType={{ type: 'default_icon_type', forceIcon: <IconBalance /> }}
                    forceBackTo={{
                        key: Scene.LegalDocuments,
                        name: 'Legal documents',
                        path: urls.legalDocuments(),
                    }}
                />
                <LemonBanner type="info">
                    <p className="mb-0">Legal documents aren't available for your organization yet.</p>
                </LemonBanner>
            </SceneContent>
        )
    }

    if (isAdminOrOwner === false) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Admin access required"
                    description="Only organization admins and owners can generate legal documents."
                    resourceType={{ type: 'default_icon_type', forceIcon: <IconBalance /> }}
                    forceBackTo={{
                        key: Scene.LegalDocuments,
                        name: 'Legal documents',
                        path: urls.legalDocuments(),
                    }}
                />
                <LemonBanner type="warning">
                    <p className="mb-0">
                        Ask one of your organization's admins or owners to sign in if you need a BAA or DPA.
                    </p>
                </LemonBanner>
            </SceneContent>
        )
    }

    const documentType = legalDocument.document_type
    const baaBlocked = documentType === 'BAA' && !hasQualifyingBaaAddon
    const headingLabel = documentType === 'BAA' ? 'New Business Associate Agreement' : 'New Data Processing Agreement'
    const submitDisabledReason = isLegalDocumentSubmitting
        ? 'Creating the PandaDoc envelope…'
        : existingDocumentOfCurrentType
          ? `Your organization already has a ${documentType}. Contact support if you need a new one.`
          : baaBlocked
            ? 'Subscribe to Boost, Scale, or Enterprise to generate a BAA'
            : documentType === 'DPA' && !isDpaModeSubmittable
              ? 'Switch to one of the legally binding formats to submit for signature'
              : legalDocumentHasErrors
                ? 'Fill in all required fields before submitting'
                : undefined

    return (
        <SceneContent>
            <SceneTitleSection
                name={headingLabel}
                description="Fill in your company details. We'll send the signing envelope through PandaDoc so you can counter-sign from email."
                resourceType={{ type: 'default_icon_type', forceIcon: <IconBalance /> }}
                forceBackTo={{
                    key: Scene.LegalDocuments,
                    name: 'Legal documents',
                    path: urls.legalDocuments(),
                }}
                actions={
                    <LemonButton
                        to={urls.legalDocuments()}
                        type="tertiary"
                        size="small"
                        disabledReason={
                            isLegalDocumentSubmitting ? 'Hang tight — your envelope is on its way' : undefined
                        }
                    >
                        Cancel
                    </LemonButton>
                }
            />

            <div className="grid gap-6 xl:grid-cols-5">
                {/* LEFT: form */}
                <section className="xl:col-span-2 bg-surface-secondary rounded-lg p-6">
                    <Form logic={legalDocumentsLogic} formKey="legalDocument" enableFormOnSubmit className="space-y-4">
                        <LemonField name="document_type" label="Document type">
                            <LemonSelect
                                options={buildDocumentTypeOptions(existingDocumentTypes)}
                                value={documentType}
                                onChange={(value) => setDocumentType(value as LegalDocumentType)}
                                fullWidth
                            />
                        </LemonField>

                        {baaBlocked && (
                            <LemonBanner type="warning">
                                A BAA requires an active{' '}
                                <Link to={urls.organizationBilling()}>Boost, Scale, or Enterprise add-on</Link>.
                                Subscribe first, then come back here to generate your BAA.
                            </LemonBanner>
                        )}

                        <LemonField name="company_name" label="Legal company name">
                            <LemonInput id={FIELD_IDS.company_name} placeholder="Acme, Inc." />
                        </LemonField>

                        <LemonField name="company_address" label="Company address">
                            <LemonInput
                                id={FIELD_IDS.company_address}
                                placeholder="1 Analytics Way, San Francisco, CA"
                            />
                        </LemonField>

                        <LemonField name="representative_email" label="Signer email">
                            <LemonInput
                                id={FIELD_IDS.representative_email}
                                type="email"
                                placeholder="jane@example.com"
                            />
                        </LemonField>

                        {documentType === 'DPA' && (
                            <div className="space-y-1">
                                <div className="text-sm font-semibold">Format</div>
                                <LemonRadio
                                    value={legalDocument.dpa_mode as DPAMode}
                                    onChange={(value) => setDpaMode(value)}
                                    options={DPA_MODE_OPTIONS}
                                    radioPosition="top"
                                />
                            </div>
                        )}

                        <div className="flex items-center justify-end gap-2 pt-2">
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                icon={<IconSend />}
                                loading={isLegalDocumentSubmitting}
                                disabledReason={submitDisabledReason}
                                data-attr="legal-documents-submit"
                            >
                                Send for signature
                            </LemonButton>
                        </div>
                    </Form>
                </section>

                {/* RIGHT: live preview */}
                <section className="xl:col-span-3 bg-surface-primary border border-border rounded-lg p-6 xl:sticky xl:top-4 xl:max-h-[calc(100vh-6rem)] xl:overflow-auto">
                    <div className="flex items-center justify-between gap-4 mb-4 pb-2 border-b border-border">
                        <h2 className="text-lg m-0 shrink-0">Preview</h2>
                        {documentType === 'DPA' && !isDpaModeSubmittable && (
                            <span className="text-xs text-warning text-right">
                                {legalDocument.dpa_mode === 'fairytale'
                                    ? "A great way to understand what the DPA says — but not something we'd send to the lawyers. Switch to one of the legally binding formats to submit."
                                    : legalDocument.dpa_mode === 'tswift'
                                      ? "Unless you know a judge who's a Swiftie, this won't hold up. Switch to one of the legally binding formats to submit for real."
                                      : 'Switch to one of the legally binding formats to submit for signature.'}
                            </span>
                        )}
                    </div>
                    <LegalDocumentsPreview />
                </section>
            </div>
        </SceneContent>
    )
}

export default LegalDocumentNewScene
