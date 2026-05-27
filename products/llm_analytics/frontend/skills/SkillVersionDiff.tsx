import { useValues } from 'kea'
import { Suspense, lazy } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonSelect } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

const MonacoDiffEditor = lazy(() => import('lib/components/MonacoDiffEditor'))

export interface SkillVersionDiffProps {
    fromVersion: number
    toVersion: number
    fromBody: string | null
    toBody: string | null
    isFromLoading?: boolean
    isToLoading?: boolean
    versionOptions: Array<{ value: number; label: string }>
    onFromVersionChange: (version: number) => void
    onToVersionChange: (version: number) => void
}

export function SkillVersionDiff({
    fromVersion,
    toVersion,
    fromBody,
    toBody,
    isFromLoading = false,
    isToLoading = false,
    versionOptions,
    onFromVersionChange,
    onToVersionChange,
}: SkillVersionDiffProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const isLoading = isFromLoading || isToLoading
    const hasBodies = fromBody !== null && toBody !== null

    return (
        <div className="mt-2 space-y-3" data-attr="llma-skill-diff-view">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-secondary">From</span>
                <LemonSelect
                    size="small"
                    value={fromVersion}
                    options={versionOptions}
                    onChange={(value) => value !== null && onFromVersionChange(value)}
                    data-attr="llma-skill-diff-from-version-select"
                />
                <IconArrowRight className="text-secondary" />
                <span className="text-sm text-secondary">To</span>
                <LemonSelect
                    size="small"
                    value={toVersion}
                    options={versionOptions}
                    onChange={(value) => value !== null && onToVersionChange(value)}
                    data-attr="llma-skill-diff-to-version-select"
                />
            </div>
            {isLoading ? (
                <div className="space-y-2 rounded border p-4">
                    <LemonSkeleton active className="h-4 w-full" />
                    <LemonSkeleton active className="h-4 w-3/4" />
                    <LemonSkeleton active className="h-4 w-1/2" />
                </div>
            ) : !hasBodies ? (
                <LemonBanner type="warning">
                    Failed to load a version for comparison. Try selecting a different version.
                </LemonBanner>
            ) : (
                <div className="overflow-hidden rounded border">
                    <Suspense
                        fallback={
                            <div className="space-y-2 p-4">
                                <LemonSkeleton active className="h-4 w-full" />
                                <LemonSkeleton active className="h-4 w-3/4" />
                            </div>
                        }
                    >
                        <MonacoDiffEditor
                            original={fromBody}
                            value={toBody}
                            modified={toBody}
                            language="markdown"
                            theme={isDarkModeOn ? 'vs-dark' : 'vs-light'}
                            options={{
                                readOnly: true,
                                renderSideBySide: true,
                                minimap: { enabled: false },
                                scrollBeyondLastLine: false,
                                wordWrap: 'on',
                                lineNumbers: 'off',
                                folding: false,
                                hideUnchangedRegions: { enabled: true },
                            }}
                        />
                    </Suspense>
                </div>
            )}
        </div>
    )
}
