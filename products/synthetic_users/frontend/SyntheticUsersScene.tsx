import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconFlask, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTextArea } from '@posthog/lemon-ui'

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

import { syntheticUsersSceneLogic } from './syntheticUsersSceneLogic'

export const scene: SceneExport = {
    component: SyntheticUsersScene,
    paramsToProps: ({ params: { id } }) => ({
        id: id && id !== 'new' ? parseInt(id) : 'new',
    }),
}

function CreateStudyModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    const { isStudyFormSubmitting, studyFormHasErrors } = useValues(syntheticUsersSceneLogic)
    const { resetStudyForm } = useActions(syntheticUsersSceneLogic)

    const handleClose = (): void => {
        resetStudyForm()
        onClose()
    }

    return (
        <LemonModal isOpen={isOpen} onClose={handleClose} title="Create new study" width={550}>
            <Form logic={syntheticUsersSceneLogic} formKey="studyForm" enableFormOnSubmit>
                <div className="space-y-4">
                    <Field name="name" label="Study name">
                        {({ value, onChange }) => (
                            <LemonInput
                                value={value}
                                onChange={onChange}
                                placeholder="e.g., Signup flow friction"
                                fullWidth
                            />
                        )}
                    </Field>

                    <Field
                        name="audience_description"
                        label="Target audience"
                        hint="Describe who you want to interview in one sentence"
                    >
                        {({ value, onChange }) => (
                            <LemonTextArea
                                value={value}
                                onChange={onChange}
                                placeholder="e.g., Marketing managers at B2B SaaS startups who are evaluating analytics tools"
                                rows={2}
                            />
                        )}
                    </Field>

                    <Field name="research_goal" label="Research goal" hint="What do you want to learn? Be specific.">
                        {({ value, onChange }) => (
                            <LemonTextArea
                                value={value}
                                onChange={onChange}
                                placeholder="e.g., Identify pain points and reasons users abandon the signup flow"
                                rows={2}
                            />
                        )}
                    </Field>

                    <Field name="target_url" label="Target URL">
                        {({ value, onChange }) => (
                            <LemonInput
                                value={value}
                                onChange={onChange}
                                placeholder="https://your-app.com/signup"
                                fullWidth
                            />
                        )}
                    </Field>

                    <p className="text-xs text-muted">
                        After creating the study, you'll start a round and choose how many sessions to run.
                    </p>

                    <div className="flex justify-end gap-2 pt-2">
                        <LemonButton type="secondary" onClick={handleClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isStudyFormSubmitting}
                            disabledReason={studyFormHasErrors ? 'Please fill in all required fields' : undefined}
                        >
                            Create study
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}

export function SyntheticUsersScene(): JSX.Element {
    const { showCreateStudyModal, studies } = useValues(syntheticUsersSceneLogic)
    const { setShowCreateStudyModal } = useActions(syntheticUsersSceneLogic)

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
                action={() => setShowCreateStudyModal(true)}
            />

            <div className="space-y-4">
                <div className="flex justify-between items-center">
                    <p className="text-muted m-0">{studies.length} studies</p>
                    <LemonButton type="primary" icon={<IconPlus />} onClick={() => setShowCreateStudyModal(true)}>
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
                            title: 'Created',
                            key: 'created_at',
                            render: (_, study) => (
                                <span className="text-sm text-muted">
                                    {new Date(study.created_at).toLocaleDateString()}
                                </span>
                            ),
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
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                onClick={() => setShowCreateStudyModal(true)}
                            >
                                Create your first study
                            </LemonButton>
                        </div>
                    }
                />
            </div>

            <CreateStudyModal isOpen={showCreateStudyModal} onClose={() => setShowCreateStudyModal(false)} />
        </SceneContent>
    )
}
