import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect, type LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { Link } from 'lib/lemon-ui/Link'
import { getExperimentVariants } from 'scenes/experiments/utils'
import { urls } from 'scenes/urls'

import { experimentScannerPickerLogic } from '../experimentScannerPickerLogic'
import { replayScannerLogic } from '../replayScannerLogic'
import type { ExperimentScannerConfig } from '../types'

export interface ExperimentScannerConfigFieldsProps {
    scannerId: string
}

/** The experiment type's scope: which experiment and variants it watches, and how it samples them. */
export function ExperimentScannerConfigFields({ scannerId }: ExperimentScannerConfigFieldsProps): JSX.Element | null {
    const logic = replayScannerLogic({ id: scannerId })
    const { scanner, isNew, experimentContext, originalScanner } = useValues(logic)
    const { setScannerExperiment } = useActions(logic)
    const { experimentOptions, experimentOptionsLoading, search } = useValues(experimentScannerPickerLogic)
    const { ensureOptionsLoaded, setSearch } = useActions(experimentScannerPickerLogic)

    const config = scanner?.scanner_type === 'experiment' ? scanner.scanner_config : null
    const experiment = experimentContext?.experiment.id === config?.experiment_id ? experimentContext?.experiment : null

    const experimentSelectOptions = useMemo((): LemonInputSelectOption[] => {
        const options = experimentOptions.map((option) => ({ key: String(option.id), label: option.name }))
        if (experiment && !options.some((option) => option.key === String(experiment.id))) {
            options.unshift({ key: String(experiment.id), label: experiment.name })
        }
        return options
    }, [experimentOptions, experiment])

    if (!config) {
        return null
    }
    const variantOptions = getExperimentVariants(experiment).map((variant) => ({
        key: variant.key,
        label: variant.key,
    }))
    const originalConfig =
        originalScanner?.scanner_type === 'experiment'
            ? (originalScanner.scanner_config as ExperimentScannerConfig)
            : null
    const balanceChanged =
        !isNew &&
        originalConfig !== null &&
        (originalConfig.balance_variants ?? true) !== (config.balance_variants ?? true)

    return (
        <div className="space-y-4">
            <LemonField
                name="scanner_config.experiment_id"
                label="Experiment"
                help={
                    experiment ? (
                        <>
                            Watches sessions of people exposed to{' '}
                            <Link to={urls.experiment(experiment.id)}>{experiment.name}</Link>. Each summary gets the
                            person's variant from exposure data.
                        </>
                    ) : (
                        "Watches sessions of people exposed to this experiment. Each summary gets the person's variant from exposure data."
                    )
                }
            >
                {() => (
                    <LemonInputSelect
                        mode="single"
                        placeholder="Select a running experiment"
                        loading={experimentOptionsLoading}
                        disabled={!isNew}
                        disabledReason={
                            isNew
                                ? undefined
                                : 'The experiment is fixed after creation. Create a new scanner to watch another experiment.'
                        }
                        disableFiltering
                        value={config.experiment_id ? [String(config.experiment_id)] : []}
                        options={experimentSelectOptions}
                        emptyStateComponent={
                            <p className="text-secondary italic p-1">
                                {search ? `No running experiments match "${search}"` : 'No running experiments'}
                            </p>
                        }
                        onFocus={() => ensureOptionsLoaded()}
                        onInputChange={(text) => setSearch(text)}
                        onChange={(values) => setScannerExperiment(values.length > 0 ? Number(values[0]) : null)}
                        data-attr="vision-experiment-scanner-picker"
                    />
                )}
            </LemonField>
            {experiment && !experiment.start_date && (
                <LemonBanner type="info">
                    This experiment hasn't launched. The scanner stays off and turns on when the experiment launches.
                </LemonBanner>
            )}
            <LemonField name="scanner_config.variants" label="Variants" help="Leave empty to watch every variant.">
                {({ value, onChange }) => (
                    <LemonInputSelect
                        mode="multiple"
                        placeholder="All variants"
                        disabledReason={experiment ? undefined : 'Select an experiment first'}
                        value={(value as string[] | null) ?? []}
                        onChange={(keys) => onChange(keys.length > 0 ? keys : null)}
                        options={variantOptions}
                        data-attr="vision-experiment-scanner-variants"
                    />
                )}
            </LemonField>
            <LemonField name="scanner_config.balance_variants">
                {({ value, onChange }) => (
                    <div className="space-y-2">
                        <div className="flex items-center gap-2">
                            <LemonSwitch
                                checked={value !== false}
                                onChange={onChange}
                                data-attr="vision-experiment-scanner-balance-variants"
                            />
                            <div>
                                <div className="text-sm font-medium">Sample variants evenly</div>
                                <div className="text-xs text-muted">
                                    Each variant gets enough sessions, even with an uneven split. Turn off to follow
                                    traffic.
                                </div>
                            </div>
                        </div>
                        {balanceChanged && (
                            <LemonBanner type="warning">
                                This change starts a new scanner version. Earlier observations keep the old sampling.
                            </LemonBanner>
                        )}
                    </div>
                )}
            </LemonField>
        </div>
    )
}
