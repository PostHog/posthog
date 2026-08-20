import { useActions, useValues } from 'kea'
import type { PropsWithChildren, UIEvent } from 'react'

import { IconClock, IconListTree } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFingerprint } from 'lib/lemon-ui/icons'
import { Tabs, TabsContent, TabsList, TabsTrigger, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { MiniBreakdowns } from '../Breakdowns/MiniBreakdowns'
import { FingerprintPreview } from '../FingerprintPreview/FingerprintPreview'
import { issueFilterPreviewLogic } from './issueFilterPreviewLogic'
import { TimeFilterPreview } from './TimeFilterPreview'

interface IssueFilterPreviewPanelProps {
    className?: string
    onScrollNearEnd?: () => void
}

export function IssueFilterPreviewPanel({
    children,
    className,
    onScrollNearEnd,
}: PropsWithChildren<IssueFilterPreviewPanelProps>): JSX.Element {
    const { activePreview } = useValues(issueFilterPreviewLogic)
    const { issueId } = useValues(errorTrackingIssueSceneLogic)
    const { setActivePreview } = useActions(issueFilterPreviewLogic)
    const hasFingerprintMap = useFeatureFlag('ERROR_TRACKING_FINGERPRINT_MAP')
    const selectedPreview = !hasFingerprintMap && activePreview === 'fingerprints' ? 'time' : activePreview

    const handleScroll = (event: UIEvent<HTMLDivElement>): void => {
        const { clientHeight, scrollHeight, scrollTop } = event.currentTarget
        if (scrollHeight - scrollTop - clientHeight <= 400) {
            onScrollNearEnd?.()
        }
    }

    return (
        <div className={className}>
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-y-none" onScroll={handleScroll}>
                <div className="max-h-1/2 shrink-0 overflow-y-auto overscroll-y-none">
                    <Tabs
                        orientation="vertical"
                        value={selectedPreview}
                        onValueChange={(preview) => {
                            if (
                                preview === 'time' ||
                                preview === 'properties' ||
                                (hasFingerprintMap && preview === 'fingerprints')
                            ) {
                                setActivePreview(preview)
                            }
                        }}
                        data-quill
                        className="relative items-stretch gap-0 bg-[var(--background)] after:pointer-events-none after:absolute after:inset-y-0 after:left-10 after:z-10 after:border-l after:border-primary after:content-['']"
                    >
                        <TabsList
                            variant="line"
                            aria-label="Issue filter previews"
                            className="sticky top-0 z-20 !h-auto w-10 shrink-0 justify-start self-start rounded-none bg-[var(--background)] p-1"
                        >
                            <Tooltip>
                                <TooltipTrigger
                                    render={
                                        <TabsTrigger
                                            value="time"
                                            aria-label="Time"
                                            className="!size-8 !flex-none !justify-center !p-0"
                                        />
                                    }
                                >
                                    <IconClock />
                                </TooltipTrigger>
                                <TooltipContent side="right">Time</TooltipContent>
                            </Tooltip>
                            <Tooltip>
                                <TooltipTrigger
                                    render={
                                        <TabsTrigger
                                            value="properties"
                                            aria-label="Properties"
                                            className="!size-8 !flex-none !justify-center !p-0"
                                        />
                                    }
                                >
                                    <IconListTree />
                                </TooltipTrigger>
                                <TooltipContent side="right">Properties</TooltipContent>
                            </Tooltip>
                            {hasFingerprintMap && (
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <TabsTrigger
                                                value="fingerprints"
                                                aria-label="Fingerprints"
                                                className="!size-8 !flex-none !justify-center !p-0"
                                            />
                                        }
                                    >
                                        <IconFingerprint />
                                    </TooltipTrigger>
                                    <TooltipContent side="right">Fingerprints</TooltipContent>
                                </Tooltip>
                            )}
                        </TabsList>
                        <TabsContent value="time" className="min-w-0 !flex-none flex-1">
                            <TimeFilterPreview />
                        </TabsContent>
                        <TabsContent value="properties" className="min-w-0 !flex-none flex-1">
                            <MiniBreakdowns />
                        </TabsContent>
                        {hasFingerprintMap && (
                            <TabsContent value="fingerprints" className="min-w-0 !flex-none flex-1">
                                <FingerprintPreview issueId={issueId} />
                            </TabsContent>
                        )}
                    </Tabs>
                </div>
                {children}
            </div>
        </div>
    )
}
