import { IconPencil, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonTable,
    LemonTableColumns,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'

import { AccessControlLevel, AccessControlResourceType, ExperimentHoldoutType } from '~/types'

import {
    DELETE_HOLDOUT_TITLE,
    HOLDOUTS_EMPTY,
    HOLDOUTS_INTRO,
    HOLDOUT_NAME_PLACEHOLDER,
    HOLDOUT_ROLLOUT_HELP,
    useHoldoutsScene,
} from './holdoutsSceneModel'
import { QuillExperimentsHoldoutsScene } from './QuillExperimentsHoldoutsScene'

export function ExperimentsHoldoutsScene(): JSX.Element {
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (todayRailNav && resultsRedesign) {
        return <QuillExperimentsHoldoutsScene />
    }
    return <LemonExperimentsHoldoutsScene />
}

function LemonExperimentsHoldoutsScene(): JSX.Element {
    const {
        holdouts,
        holdoutsLoading,
        holdout,
        setHoldout,
        isModalOpen: isHoldoutModalOpen,
        editingHoldout,
        openEditModal,
        openCreateModal,
        closeModal,
        save,
        saveDisabledReason,
        rolloutPercentage,
        setRolloutPercentage,
        deleteHoldout,
    } = useHoldoutsScene()

    const columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: (name: string) => <div className="font-semibold">{name}</div>,
        },
        {
            title: 'Description',
            dataIndex: 'description',
            key: 'description',
        },
        {
            title: 'Rollout Percentage',
            dataIndex: 'filters',
            key: 'rollout',
            render: (filters: ExperimentHoldoutType['filters']) => {
                const percentage = filters?.[0]?.rollout_percentage || 0
                return <div>{percentage} %</div>
            },
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_: any, record: ExperimentHoldoutType) => (
                <div className="flex gap-2">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.ExperimentHoldout}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={record.user_access_level}
                    >
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            icon={<IconPencil />}
                            onClick={() => openEditModal(record)}
                        />
                    </AccessControlAction>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.ExperimentHoldout}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={record.user_access_level}
                    >
                        <LemonButton
                            type="secondary"
                            icon={<IconTrash />}
                            size="xsmall"
                            status="danger"
                            onClick={() => {
                                LemonDialog.open({
                                    title: DELETE_HOLDOUT_TITLE,
                                    content: (
                                        <div className="text-sm">
                                            Are you sure you want to delete the holdout <b>"{record.name}"</b>? This
                                            action cannot be undone.
                                        </div>
                                    ),
                                    primaryButton: {
                                        children: 'Delete',
                                        type: 'primary',
                                        status: 'danger',
                                        onClick: () => deleteHoldout(record.id),
                                        size: 'small',
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                        type: 'tertiary',
                                        size: 'small',
                                    },
                                })
                            }}
                        />
                    </AccessControlAction>
                </div>
            ),
        },
    ]

    return (
        <div className="deprecated-space-y-4">
            <LemonModal
                isOpen={isHoldoutModalOpen}
                onClose={closeModal}
                title={editingHoldout ? 'Edit holdout' : 'Add holdout'}
                footer={
                    <>
                        <LemonButton onClick={closeModal}>Cancel</LemonButton>
                        <LemonButton type="primary" onClick={save} disabledReason={saveDisabledReason}>
                            {editingHoldout ? 'Update' : 'Save'}
                        </LemonButton>
                    </>
                }
            >
                <div className="deprecated-space-y-4">
                    <div>
                        <LemonLabel>Name</LemonLabel>
                        <LemonInput
                            value={holdout.name}
                            onChange={(name) => setHoldout({ name })}
                            placeholder={HOLDOUT_NAME_PLACEHOLDER}
                        />
                    </div>
                    <div>
                        <LemonLabel>Description</LemonLabel>
                        <LemonInput
                            value={holdout.description || ''}
                            onChange={(description) => setHoldout({ description })}
                        />
                    </div>
                    <div>
                        <LemonDivider />
                        <LemonBanner type="info">
                            <div className="deprecated-space-y-2">
                                <div>{HOLDOUT_ROLLOUT_HELP}</div>
                            </div>
                        </LemonBanner>
                        <div className="mt-4 flex flex-wrap items-center gap-1">
                            Roll out to{' '}
                            <LemonSlider
                                value={rolloutPercentage}
                                onChange={setRolloutPercentage}
                                min={0}
                                max={100}
                                step={1}
                                className="ml-1.5 w-20"
                            />
                            <LemonInput
                                data-attr="rollout-percentage"
                                type="number"
                                className="ml-2 mr-1.5 max-w-30"
                                value={rolloutPercentage}
                                onChange={setRolloutPercentage}
                                min={0}
                                max={100}
                                step="any"
                                suffix={<span>%</span>}
                            />
                            of <b>total users.</b>
                        </div>
                    </div>
                </div>
            </LemonModal>

            <LemonBanner type="info">
                <div className="deprecated-space-y-2">
                    <div>{HOLDOUTS_INTRO}</div>
                </div>
            </LemonBanner>
            <div className="flex justify-end">
                <LemonButton type="primary" onClick={openCreateModal} data-attr="add-holdout">
                    New holdout
                </LemonButton>
            </div>

            <LemonTable
                emptyState={<div className="py-4 text-secondary text-sm text-center">{HOLDOUTS_EMPTY}</div>}
                loading={holdoutsLoading}
                dataSource={holdouts}
                columns={columns as LemonTableColumns<ExperimentHoldoutType>}
            />
        </div>
    )
}
