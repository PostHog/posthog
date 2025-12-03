import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconChevronDown, IconMagicWand, IconMessage } from '@posthog/icons'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorTrackingException } from 'lib/components/Errors/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItemIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { urls } from 'scenes/urls'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { errorTrackingIssueSceneLogic } from 'products/error_tracking/frontend/scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'

import { ExceptionAttributesPreview } from '../../ExceptionAttributesPreview'
import { useErrorTrackingExplainIssueMaxTool } from '../../ExplainIssueTool'
import { ReleasePreviewPill } from '../../ReleasesPreview/ReleasePreviewPill'
import { FixModal } from '../FixModal'
import { StacktraceBaseDisplayProps, StacktraceEmptyDisplay } from '../Stacktrace/StacktraceBase'
import { StacktraceGenericDisplay } from '../Stacktrace/StacktraceGenericDisplay'
import { StacktraceTextDisplay } from '../Stacktrace/StacktraceTextDisplay'
import { exceptionCardLogic } from '../exceptionCardLogic'
import { SubHeader } from './SubHeader'

export interface StacktraceTabProps extends Omit<TabsPrimitiveContentProps, 'children'> {
    issue?: ErrorTrackingRelationalIssue
    issueLoading: boolean
    timestamp?: string
}

export function StacktraceTab({
    className,
    issue,
    issueLoading,
    timestamp,
    ...props
}: StacktraceTabProps): JSX.Element {
    const { loading, issueId } = useValues(exceptionCardLogic)
    const { setShowAllFrames } = useActions(exceptionCardLogic)
    const { exceptionAttributes, exceptionList, hasStacktrace, hasInAppFrames, exceptionType, release } =
        useValues(errorPropertiesLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const showFixButton = hasResolvedStackFrames(exceptionList)
    const [showFixModal, setShowFixModal] = useState(false)
    const [showSurveyModal, setShowSurveyModal] = useState(false)
    const { openMax } = useErrorTrackingExplainIssueMaxTool(issueId, exceptionType)

    useEffect(() => {
        if (!loading) {
            if (hasStacktrace && !hasInAppFrames) {
                setShowAllFrames(true)
            }
        }
    }, [loading, hasStacktrace, hasInAppFrames, setShowAllFrames])

    const exceptionSurveys = surveysByIssueId[issueId] ?? []
    const hasExceptionSurveys = exceptionSurveys.length > 0
    const showSurveyButton = featureFlags[FEATURE_FLAGS.SURVEYS_ERROR_TRACKING_CROSS_SELL] && !exceptionSurveysLoading

    const handleSurveyClick = (): void => {
        if (!hasExceptionSurveys) {
            setShowSurveyModal(true)
        } else if (exceptionSurveys.length === 1) {
            router.actions.push(urls.survey(exceptionSurveys[0].id))
        } else {
            router.actions.push(urls.surveys())
        }
    }

    return (
        <TabsPrimitiveContent {...props}>
            <SubHeader className="justify-between">
                <div className="flex items-center gap-1">
                    <ExceptionAttributesPreview attributes={exceptionAttributes} loading={loading} />
                    {release && <ReleasePreviewPill release={release} />}
                </div>
                <ButtonGroupPrimitive size="sm">
                    {showSurveyButton && (
                        <ButtonPrimitive
                            onClick={handleSurveyClick}
                            className="px-2 h-[1.4rem]"
                            tooltip={
                                !hasExceptionSurveys ? 'Show a survey to users when this exception occurs' : undefined
                            }
                        >
                            <IconMessage />
                            {!hasExceptionSurveys ? 'Ask affected users' : 'View feedback'}
                        </ButtonPrimitive>
                    )}
                    {showFixButton && (
                        <ButtonPrimitive
                            onClick={() => setShowFixModal(true)}
                            className="px-2 h-[1.4rem]"
                            tooltip="Generate AI prompt to fix this error"
                        >
                            <IconMagicWand />
                            Get AI prompt
                        </ButtonPrimitive>
                    )}
                    {openMax && (
                        <ButtonPrimitive
                            onClick={() => openMax()}
                            className="px-2 h-[1.4rem]"
                            tooltip="Ask PostHog AI for an explanation of this issue"
                        >
                            <IconMagicWand />
                            Explain this issue
                        </ButtonPrimitive>
                    )}
                    <ShowDropDownMenu>
                        <ButtonPrimitive className="px-2 h-[1.4rem]">
                            Show
                            <IconChevronDown />
                        </ButtonPrimitive>
                    </ShowDropDownMenu>
                </ButtonGroupPrimitive>
            </SubHeader>
            <StacktraceIssueDisplay
                className="p-2"
                truncateMessage={false}
                issue={issue ?? undefined}
                issueLoading={issueLoading}
            />
            <FixModal isOpen={showFixModal} onClose={() => setShowFixModal(false)} issueId={issueId} />
            <QuickSurveyModal
                context={{
                    type: QuickSurveyType.ERROR_TRACKING,
                    issueId: issueId,
                }}
                info="This survey will display when a user encounters this exception."
                isOpen={showSurveyModal}
                onCancel={() => setShowSurveyModal(false)}
            />
        </TabsPrimitiveContent>
    )
}

function StacktraceIssueDisplay({
    issue,
    issueLoading,
    ...stacktraceDisplayProps
}: {
    issue?: ErrorTrackingRelationalIssue
    issueLoading: boolean
} & Omit<StacktraceBaseDisplayProps, 'renderEmpty'>): JSX.Element {
    const { showAsText } = useValues(exceptionCardLogic)
    const componentProps = {
        ...stacktraceDisplayProps,
        renderEmpty: () => <StacktraceEmptyDisplay />,
    }
    return showAsText ? <StacktraceTextDisplay {...componentProps} /> : <StacktraceGenericDisplay {...componentProps} />
}

function ShowDropDownMenu({ children }: { children: React.ReactNode }): JSX.Element {
    const { showAllFrames, showAsText } = useValues(exceptionCardLogic)
    const { setShowAllFrames, setShowAsText } = useActions(exceptionCardLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>{children}</DropdownMenuTrigger>
            <DropdownMenuContent>
                <DropdownMenuGroup>
                    <DropdownMenuCheckboxItem checked={showAllFrames} onCheckedChange={setShowAllFrames} asChild>
                        <ButtonPrimitive menuItem size="sm">
                            <DropdownMenuItemIndicator intent="checkbox" />
                            All frames
                        </ButtonPrimitive>
                    </DropdownMenuCheckboxItem>
                    <DropdownMenuCheckboxItem checked={showAsText} onCheckedChange={setShowAsText} asChild>
                        <ButtonPrimitive menuItem size="sm">
                            <DropdownMenuItemIndicator intent="checkbox" />
                            As text
                        </ButtonPrimitive>
                    </DropdownMenuCheckboxItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

// Helper function to check if any exception has resolved stack frames
function hasResolvedStackFrames(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList.some((exception) => {
        if (exception.stacktrace?.type === 'resolved' && exception.stacktrace?.frames) {
            return exception.stacktrace.frames.some((frame) => frame.resolved)
        }
        return false
    })
}
