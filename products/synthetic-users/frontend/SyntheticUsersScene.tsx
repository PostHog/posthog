import { router } from 'kea-router'
import { useState } from 'react'

import { IconFlask, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { RobotHog } from 'lib/components/hedgehogs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { MOCK_STUDY_SUMMARIES } from './fixtures'
import type { RoundStatus, StudySummary } from './types'

export const scene: SceneExport = {
    component: SyntheticUsersScene,
}

function StudyStatusTag({ status }: { status: RoundStatus | null }): JSX.Element {
    if (!status) {
        return <LemonTag type="muted">No rounds</LemonTag>
    }
    const config: Record<
        RoundStatus,
        { type: 'muted' | 'option' | 'completion' | 'success' | 'danger'; label: string }
    > = {
        draft: { type: 'muted', label: 'Draft' },
        generating: { type: 'option', label: 'Generating...' },
        running: { type: 'completion', label: 'Running...' },
        completed: { type: 'success', label: 'Completed' },
        failed: { type: 'danger', label: 'Failed' },
    }
    return <LemonTag type={config[status].type}>{config[status].label}</LemonTag>
}

function CreateStudyModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    const [name, setName] = useState('')
    const [audience, setAudience] = useState('')
    const [goal, setGoal] = useState('')
    const [url, setUrl] = useState('')

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="Create new study" width={550}>
            <div className="space-y-4">
                <div>
                    <label className="text-sm font-medium">Study name</label>
                    <LemonInput
                        value={name}
                        onChange={setName}
                        placeholder="e.g., Signup flow friction"
                        fullWidth
                        className="mt-1"
                    />
                </div>

                <div>
                    <label className="text-sm font-medium">Target audience</label>
                    <p className="text-xs text-muted mt-0.5 mb-1">Describe who you want to interview in one sentence</p>
                    <LemonTextArea
                        value={audience}
                        onChange={setAudience}
                        placeholder="e.g., Marketing managers at B2B SaaS startups who are evaluating analytics tools"
                        rows={2}
                    />
                </div>

                <div>
                    <label className="text-sm font-medium">Research goal</label>
                    <p className="text-xs text-muted mt-0.5 mb-1">What do you want to learn? Be specific.</p>
                    <LemonTextArea
                        value={goal}
                        onChange={setGoal}
                        placeholder="e.g., Identify pain points and reasons users abandon the signup flow"
                        rows={2}
                    />
                </div>

                <div>
                    <label className="text-sm font-medium">Target URL</label>
                    <LemonInput
                        value={url}
                        onChange={setUrl}
                        placeholder="https://your-app.com/signup"
                        fullWidth
                        className="mt-1"
                    />
                </div>

                <p className="text-xs text-muted">
                    After creating the study, you'll start a round and choose how many sessions to run.
                </p>

                <div className="flex justify-end gap-2 pt-2">
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={onClose}
                        disabledReason={
                            !name
                                ? 'Enter a study name'
                                : !audience
                                  ? 'Describe your target audience'
                                  : !goal
                                    ? 'Enter your research goal'
                                    : !url
                                      ? 'Enter the target URL'
                                      : undefined
                        }
                    >
                        Create study
                    </LemonButton>
                </div>
            </div>
        </LemonModal>
    )
}

export function SyntheticUsersScene(): JSX.Element {
    const [showCreateStudy, setShowCreateStudy] = useState(false)

    const studies: StudySummary[] = MOCK_STUDY_SUMMARIES

    return (
        <SceneContent>
            <SceneTitleSection
                name="Synthetic users"
                description="Run UX research with AI-generated users"
                resourceType={{ type: 'persons' }}
            />

            <ProductIntroduction
                productName="Synthetic users"
                productKey={ProductKey.SYNTHETIC_USERS}
                thingName="study"
                description="Run UX research with AI-generated users. Describe your target audience and research goal, then let synthetic users navigate your product and report back with insights — no recruiting, scheduling, or incentives required."
                customHog={RobotHog}
                isEmpty={studies.length === 0}
                action={() => setShowCreateStudy(true)}
            />

            <div className="space-y-4">
                <div className="flex justify-between items-center">
                    <p className="text-muted m-0">{studies.length} studies</p>
                    <LemonButton type="primary" icon={<IconPlus />} onClick={() => setShowCreateStudy(true)}>
                        New study
                    </LemonButton>
                </div>

                <LemonTable
                    dataSource={studies}
                    onRow={(study) => ({
                        onClick: () => router.actions.push(urls.syntheticUsersStudy(study.id)),
                        className: 'cursor-pointer',
                    })}
                    columns={[
                        {
                            title: 'Study',
                            key: 'name',
                            render: (_, study) => (
                                <LemonTableLink
                                    title={
                                        <span className="flex items-center gap-2">
                                            <IconFlask className="text-muted" />
                                            {study.name}
                                        </span>
                                    }
                                    description={study.research_goal}
                                    to={urls.syntheticUsersStudy(study.id)}
                                />
                            ),
                        },
                        {
                            title: 'Audience',
                            key: 'audience',
                            render: (_, study) => (
                                <span className="text-sm text-muted truncate max-w-xs block">
                                    {study.audience_description}
                                </span>
                            ),
                        },
                        {
                            title: 'Rounds',
                            key: 'rounds',
                            render: (_, study) => <span>{study.rounds_count || '—'}</span>,
                        },
                        {
                            title: 'Sessions',
                            key: 'sessions',
                            render: (_, study) => <span>{study.total_sessions || '—'}</span>,
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: (_, study) => <StudyStatusTag status={study.latest_round_status} />,
                        },
                        {
                            width: 0,
                            render: (_, study) => (
                                <More
                                    onClick={(e) => e.stopPropagation()}
                                    overlay={
                                        <LemonMenuOverlay
                                            items={[
                                                {
                                                    label: 'View details',
                                                    onClick: () =>
                                                        router.actions.push(urls.syntheticUsersStudy(study.id)),
                                                },
                                                { label: 'Duplicate', onClick: () => {} },
                                                {
                                                    label: 'Delete',
                                                    status: 'danger' as const,
                                                    icon: <IconTrash />,
                                                    onClick: () => {},
                                                },
                                            ]}
                                        />
                                    }
                                />
                            ),
                        },
                    ]}
                    rowKey="id"
                    emptyState={
                        <div className="text-center py-8">
                            <IconFlask className="w-12 h-12 text-muted mx-auto mb-4" />
                            <h3 className="text-lg font-semibold mb-2">No studies yet</h3>
                            <p className="text-muted mb-4">
                                Create a study to run UX research with AI-generated users.
                            </p>
                            <LemonButton type="primary" icon={<IconPlus />} onClick={() => setShowCreateStudy(true)}>
                                Create your first study
                            </LemonButton>
                        </div>
                    }
                />
            </div>

            <CreateStudyModal isOpen={showCreateStudy} onClose={() => setShowCreateStudy(false)} />
        </SceneContent>
    )
}
