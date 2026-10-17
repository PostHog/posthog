import clsx from 'clsx'
import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonTag, Link, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { Label } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ExperimentStatsMethod } from '~/types'

import { StatusTag } from 'products/experiments/frontend/components/StatusTag'
import { CONCLUSION_DISPLAY_CONFIG } from 'products/experiments/frontend/constants'
import { getExperimentStatus, isExperimentPaused } from 'products/experiments/frontend/experimentStatus'
import { isSingleVariantShipped, getShippedVariantKey } from 'products/experiments/frontend/scenes/experimentsLogic'

import { LegacyExperimentDates } from './LegacyExperimentDates'

export function LegacyExperimentInfo(): JSX.Element | null {
    const { experiment } = useValues(experimentLogic)

    const { created_by } = experiment

    const statsMethod = experiment.stats_config?.method || ExperimentStatsMethod.Bayesian

    if (!experiment.feature_flag) {
        return null
    }

    const status = getExperimentStatus(experiment)
    const isPaused = isExperimentPaused(experiment)

    return (
        <SceneContent>
            <div className="flex flex-wrap justify-between gap-4">
                <div className="inline-flex deprecated-space-x-8">
                    <div className="flex flex-col" data-attr="experiment-status">
                        <Label intent="menu">Status</Label>
                        <div className="flex gap-1">
                            <StatusTag status={status} />
                            {isSingleVariantShipped(experiment) && (
                                <Tooltip
                                    title={`Variant "${getShippedVariantKey(experiment)}" has been rolled out to 100% of users`}
                                >
                                    <LemonTag type="completion" className="cursor-default">
                                        <b className="uppercase">100% rollout</b>
                                    </LemonTag>
                                </Tooltip>
                            )}
                        </div>
                    </div>
                    {experiment.feature_flag && (
                        <div className="flex flex-col">
                            <Label intent="menu">Feature flag</Label>
                            <div className="flex gap-1 items-center">
                                {isPaused && (
                                    <Tooltip
                                        placement="bottom"
                                        title="Your experiment is paused. The linked flag is disabled and no data is being collected."
                                    >
                                        <IconWarning
                                            style={{ transform: 'translateY(2px)' }}
                                            className="mr-1 text-danger"
                                            fontSize="18px"
                                        />
                                    </Tooltip>
                                )}
                                <CopyToClipboardInline
                                    iconStyle={{ color: 'var(--lemon-button-icon-opacity)' }}
                                    className="font-normal text-sm"
                                    description="feature flag key"
                                >
                                    {experiment.feature_flag.key}
                                </CopyToClipboardInline>
                                <Link
                                    target="_blank"
                                    className="font-semibold"
                                    to={
                                        experiment.feature_flag
                                            ? urls.featureFlag(experiment.feature_flag.id)
                                            : undefined
                                    }
                                >
                                    <IconOpenInNew fontSize="18" />
                                </Link>
                            </div>
                        </div>
                    )}
                    <div className="flex flex-col">
                        <Label intent="menu">Stats Engine</Label>
                        <div className="inline-flex deprecated-space-x-2">
                            <span>{statsMethod === ExperimentStatsMethod.Bayesian ? 'Bayesian' : 'Frequentist'}</span>
                        </div>
                    </div>
                </div>

                <div className="flex flex-col">
                    <div className="inline-flex deprecated-space-x-8">
                        <LegacyExperimentDates />
                        <div className="flex flex-col">
                            <Label intent="menu">Created by</Label>
                            {created_by && <ProfilePicture user={created_by} size="md" showName />}
                        </div>
                    </div>
                </div>
            </div>
            <div className={cn('block mt-0')}>
                <div className="flex gap-6">
                    <div className="w-[500px]">
                        <div className="flex items-center gap-2">
                            <Label intent="menu">Hypothesis</Label>
                        </div>
                        {experiment.description ? (
                            <p className={cn('py-2 m-0')}>{experiment.description}</p>
                        ) : (
                            <p className={cn('py-2 m-0 text-secondary')}>Add your hypothesis for this test</p>
                        )}
                    </div>
                    {experiment.conclusion && experiment.end_date && (
                        <div className="w-[500px]">
                            <div className="flex items-center gap-2">
                                <Label intent="menu">Conclusion</Label>
                            </div>
                            <div className={cn('py-0')}>
                                <div className="font-semibold flex items-center gap-2">
                                    <div
                                        className={clsx(
                                            'w-2 h-2 rounded-full',
                                            CONCLUSION_DISPLAY_CONFIG[experiment.conclusion]?.color || ''
                                        )}
                                    />
                                    <span>
                                        {CONCLUSION_DISPLAY_CONFIG[experiment.conclusion]?.title ||
                                            experiment.conclusion}
                                    </span>
                                </div>
                                <div>{experiment.conclusion_comment}</div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}
