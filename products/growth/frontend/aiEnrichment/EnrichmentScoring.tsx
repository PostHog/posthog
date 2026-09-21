import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonTag,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditor } from 'lib/monaco/CodeEditor'

import type { ScoringConfigApi } from '../generated/api.schemas'
import { suggestNextVersion } from './aiEnrichmentVersioning'
import { enrichmentScoringLogic } from './enrichmentScoringLogic'
import { EnrichmentScoringResults } from './EnrichmentScoringResults'

export function EnrichmentScoring(): JSX.Element {
    const {
        configs,
        configsLoading,
        versions,
        activeConfig,
        selectedConfig,
        source,
        isDirty,
        isSaving,
        previewLoading,
        preview,
        savedConfigLoading,
        activatedConfigLoading,
        loadError,
        actionError,
    } = useValues(enrichmentScoringLogic)
    const { loadConfigs, selectConfig, setSource, previewFormula, saveFormula, activateFormula } =
        useActions(enrichmentScoringLogic)

    if (!configs && !loadError) {
        return <LemonSkeleton className="h-80" />
    }
    if (loadError) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadConfigs() }}>
                Could not load scoring formulas. Try again.
            </LemonBanner>
        )
    }

    const selectVersion = (config: ScoringConfigApi): void => {
        if (!isDirty) {
            selectConfig(config)
            return
        }
        LemonDialog.open({
            title: 'Discard unsaved formula changes?',
            description: `Viewing version ${config.version} will replace your current edits.`,
            primaryButton: {
                children: 'Discard changes',
                status: 'danger',
                onClick: () => selectConfig(config),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }
    const disabledReason = isSaving
        ? 'Wait for the current change to finish'
        : !selectedConfig
          ? 'Set up the initial scoring configuration first'
          : !source.trim()
            ? 'Enter a scoring formula'
            : undefined

    return (
        <div className="space-y-4 min-w-0">
            <div>
                <h3>ICP scoring formula</h3>
                <p className="text-secondary mb-0">
                    Edit how company facts and AI labels contribute to the score. Test against saved inputs, then save
                    and activate a version.
                </p>
            </div>
            {!selectedConfig && (
                <LemonBanner type="info">
                    Set up the initial scoring configuration and its company lists before testing or saving a formula.
                </LemonBanner>
            )}
            <div className="flex flex-wrap items-center gap-2">
                <LemonSelect
                    value={selectedConfig?.id}
                    options={versions.map((config) => ({
                        value: config.id,
                        label: `${config.version}${config.is_active ? ' (active)' : ''}`,
                    }))}
                    onChange={(id) => {
                        const config = versions.find((item) => item.id === id)
                        if (config) {
                            selectVersion(config)
                        }
                    }}
                    disabledReason={isSaving || configsLoading ? 'Wait for the current change to finish' : undefined}
                    placeholder="No saved versions"
                    data-attr="enrichment-scoring-version"
                />
                <span className="text-secondary text-sm">{`Active version: ${activeConfig?.version ?? 'None'}`}</span>
                {isDirty && <LemonTag type="warning">Unsaved changes</LemonTag>}
                {selectedConfig && !selectedConfig.is_active && !isDirty && <LemonTag>Draft</LemonTag>}
            </div>
            <div className="space-y-2">
                <p className="text-secondary text-sm mb-0">
                    Use variables such as <code>company</code>, <code>ai_pilled</code>, and <code>wizard_ai_sdk</code>.
                    Return <code>status</code>, <code>score</code>, and <code>components</code>. Expand a sample company
                    below to inspect all available inputs.
                </p>
                <CodeEditor
                    key={selectedConfig?.id ?? 'default'}
                    className="border rounded min-w-0"
                    language="hog"
                    globals={
                        preview?.response.results[0]?.inputs ?? {
                            company: {},
                            tags: [],
                            tag_types: [],
                            investors: [],
                            lists: {},
                            role: '',
                            domain: '',
                            wizard_ai_sdk: false,
                            ai_pilled: false,
                        }
                    }
                    value={source}
                    onChange={(value) => setSource(value ?? '')}
                    height={360}
                    options={{
                        minimap: { enabled: false },
                        wordWrap: 'on',
                        readOnly: isSaving,
                        scrollBeyondLastLine: false,
                    }}
                />
            </div>
            {actionError && <LemonBanner type="error">{actionError}</LemonBanner>}
            <div className="flex flex-wrap items-center gap-2">
                <LemonButton
                    type="primary"
                    loading={previewLoading}
                    disabledReason={disabledReason}
                    onClick={() => previewFormula()}
                    data-attr="enrichment-scoring-preview"
                >
                    Test 10 companies
                </LemonButton>
                <LemonButton
                    type="secondary"
                    loading={savedConfigLoading}
                    disabledReason={disabledReason}
                    onClick={() =>
                        LemonDialog.openForm({
                            title: 'Save scoring formula',
                            description:
                                'This saves a new version. Activate it separately to use it for future scoring runs.',
                            initialValues: { version: suggestNextVersion(versions) },
                            content: (
                                <LemonField name="version" label="Version">
                                    <LemonInput autoFocus />
                                </LemonField>
                            ),
                            errors: { version: (value) => (!value?.trim() ? 'Enter a version name' : undefined) },
                            onSubmit: ({ version }) => saveFormula(version),
                        })
                    }
                    data-attr="enrichment-scoring-save"
                >
                    Save as new version
                </LemonButton>
                {selectedConfig && !selectedConfig.is_active && (
                    <LemonButton
                        type="secondary"
                        loading={activatedConfigLoading}
                        disabledReason={disabledReason ?? (isDirty ? 'Save your changes before activating' : undefined)}
                        onClick={() =>
                            LemonDialog.open({
                                title: `Activate formula ${selectedConfig.version}?`,
                                description:
                                    'Future scoring runs will use this formula. Existing scores will change when those companies are scored again.',
                                primaryButton: {
                                    children: 'Activate',
                                    onClick: () => activateFormula(selectedConfig.id),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                        data-attr="enrichment-scoring-activate"
                    >
                        Activate
                    </LemonButton>
                )}
            </div>
            <p className="text-secondary text-xs">
                Preview uses saved company facts and AI labels. It does not fetch websites, call a model, or save
                scores.
            </p>
            <EnrichmentScoringResults />
        </div>
    )
}
