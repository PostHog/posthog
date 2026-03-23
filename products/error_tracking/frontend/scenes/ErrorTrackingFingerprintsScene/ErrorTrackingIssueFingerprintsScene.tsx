import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { IconGitBranch } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { CollapsibleExceptionList } from 'lib/components/Errors/ExceptionList/CollapsibleExceptionList'
import { ErrorEventProperties } from 'lib/components/Errors/types'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'

import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { errorTrackingIssueFingerprintsSceneLogic } from './errorTrackingIssueFingerprintsSceneLogic'

export type ErrorTrackingFingerprintSamples = {
    fingerprint: string
    count: number
    samples: { type: string; value: string }[]
}

export interface ErrorTrackingIssueFingerprintsSceneProps {
    id: string
}

export const scene: SceneExport<ErrorTrackingIssueFingerprintsSceneProps> = {
    component: ErrorTrackingIssueFingerprintsScene,
    logic: errorTrackingIssueFingerprintsSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function ErrorTrackingIssueFingerprintsScene(): JSX.Element {
    const { issue, issueFingerprints, fingerprintSamples, isLoading, unmergingFingerprints } = useValues(
        errorTrackingIssueFingerprintsSceneLogic
    )
    const { loadFingerprintSamples, unmerge } = useActions(errorTrackingIssueFingerprintsSceneLogic)

    useEffect(() => {
        if (issue && issueFingerprints) {
            loadFingerprintSamples(issue, issueFingerprints)
        }
    }, [issue, issueFingerprints, loadFingerprintSamples])

    const fingerprintCreatedAt = useMemo(
        () => new Map((issueFingerprints ?? []).map((f) => [f.fingerprint, f.created_at])),
        [issueFingerprints]
    )

    const columns = [
        {
            title: 'Exception type',
            key: 'type',
            dataIndex: 'samples',
            width: '200px',
            render: (samples: { type: string; value: string }[]) =>
                samples.length > 0 ? samples[0].type : <span className="text-muted italic">Unknown</span>,
        },
        {
            title: 'Exception message',
            key: 'message',
            dataIndex: 'samples',
            render: (messages: { type: string; value: string }[]) =>
                messages.length > 0 ? messages[0].value : <span className="text-muted italic">No message</span>,
        },
        { title: 'Occurrences', dataIndex: 'count' },
        {
            key: 'unmerge',
            width: '30px',
            render: (_, record) => (
                <LemonButton
                    size="xsmall"
                    type="primary"
                    icon={<IconGitBranch />}
                    tooltip="Unmerge"
                    disabledReason={
                        fingerprintSamples.length === 1
                            ? 'This issue only has one fingerprint and cannot be unmerged'
                            : unmergingFingerprints.has(record.fingerprint)
                              ? 'Unmerging in progress...'
                              : undefined
                    }
                    onClick={() => unmerge(record.fingerprint)}
                />
            ),
        },
    ] as LemonTableColumns<ErrorTrackingFingerprintSamples>

    return (
        <ErrorTrackingSetupPrompt>
            <SceneContent className="pt-4">
                <SceneTitleSection
                    name="Fingerprints"
                    description={null}
                    resourceType={{ type: 'error_tracking' }}
                    actions={
                        <LemonButton
                            size="small"
                            type="secondary"
                            to="https://posthog.com/docs/error-tracking/fingerprints"
                            targetBlank
                        >
                            Documentation
                        </LemonButton>
                    }
                />
                <div className="space-y-2">
                    <div className="text-secondary">
                        Unmerge fingerprints into separate issues. Each unmerged fingerprint becomes its own issue.
                    </div>
                    <LemonTable<ErrorTrackingFingerprintSamples>
                        className="w-full mt-4"
                        loading={isLoading}
                        dataSource={fingerprintSamples}
                        columns={columns}
                        rowKey="fingerprint"
                        expandable={{
                            noIndent: true,
                            expandedRowRender: (record) => (
                                <FingerprintStackTrace
                                    fingerprint={record.fingerprint}
                                    createdAt={fingerprintCreatedAt.get(record.fingerprint)}
                                />
                            ),
                        }}
                    />
                </div>
            </SceneContent>
        </ErrorTrackingSetupPrompt>
    )
}

function getOneHourWindow(timestamp: string): { after: string; before: string } {
    const date = new Date(timestamp)
    const after = new Date(date.getTime() - 30 * 60 * 1000).toISOString()
    const before = new Date(date.getTime() + 30 * 60 * 1000).toISOString()
    return { after, before }
}

function FingerprintStackTrace({ fingerprint, createdAt }: { fingerprint: string; createdAt?: string }): JSX.Element {
    const [properties, setProperties] = useState<ErrorEventProperties | null>(null)
    const [eventId, setEventId] = useState<string | null>(null)
    const [loading, setLoading] = useState(true)

    const fetchEvent = useCallback(async () => {
        setLoading(true)
        try {
            const timeWindow = createdAt ? getOneHourWindow(createdAt) : {}
            const query: EventsQuery = {
                kind: NodeKind.EventsQuery,
                event: '$exception',
                select: ['uuid', 'properties'],
                ...timeWindow,
                where: [
                    `properties.$exception_fingerprint = '${fingerprint.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`,
                ],
                orderBy: ['timestamp ASC'],
                limit: 1,
            }
            const response = await api.query(query)
            if (response.results.length > 0) {
                const [uuid, props] = response.results[0]
                setEventId(uuid)
                setProperties(typeof props === 'string' ? JSON.parse(props) : props)
            }
        } finally {
            setLoading(false)
        }
    }, [fingerprint])

    useEffect(() => {
        void fetchEvent()
    }, [fetchEvent])

    const eventProps = useMemo(
        () => ({ properties: properties ?? undefined, id: eventId ?? fingerprint }) as ErrorPropertiesLogicProps,
        [properties, eventId, fingerprint]
    )

    if (loading) {
        return (
            <div className="p-4 space-y-2">
                <LemonSkeleton className="h-4 w-1/3" />
                <LemonSkeleton className="h-4 w-full" />
                <LemonSkeleton className="h-4 w-2/3" />
            </div>
        )
    }

    if (!properties) {
        return <div className="p-4 text-muted italic">No stack trace available</div>
    }

    return (
        <BindLogic logic={errorPropertiesLogic} props={eventProps}>
            <StackTraceDisplay />
        </BindLogic>
    )
}

function StackTraceDisplay(): JSX.Element {
    const [showAllFrames, setShowAllFrames] = useState(false)
    const [expandedFrameRawIds, setExpandedFrameRawIds] = useState<Set<string>>(new Set())
    const { hasInAppFrames } = useValues(errorPropertiesLogic)

    useEffect(() => {
        if (!hasInAppFrames) {
            setShowAllFrames(true)
        }
    }, [hasInAppFrames])

    const handleFrameExpandedChange = useCallback((rawId: string, expanded: boolean) => {
        setExpandedFrameRawIds((prev) => {
            const next = new Set(prev)
            if (expanded) {
                next.add(rawId)
            } else {
                next.delete(rawId)
            }
            return next
        })
    }, [])

    return (
        <CollapsibleExceptionList
            showAllFrames={showAllFrames}
            setShowAllFrames={setShowAllFrames}
            expandedFrameRawIds={expandedFrameRawIds}
            onFrameExpandedChange={handleFrameExpandedChange}
            className="p-2"
        />
    )
}
