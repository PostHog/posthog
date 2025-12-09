import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, RoleType } from '~/types'

import { productAreasLogic } from './productAreasLogic'

export function ProductAreaModal(): JSX.Element {
    const { isModalOpen, editingProductArea, modalName, modalRoleId, roles, isSaving } = useValues(productAreasLogic)
    const { closeModal, setModalName, setModalRoleId, saveProductArea } = useActions(productAreasLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const isEditing = !!editingProductArea
    const hasRolesFeature = hasAvailableFeature(AvailableFeature.ROLE_BASED_ACCESS)

    const roleOptions = [
        { value: null, label: 'No team' },
        ...roles.map((role: RoleType) => ({ value: role.id, label: role.name })),
    ]

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            title={isEditing ? 'Edit product area' : 'New product area'}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveProductArea}
                        loading={isSaving}
                        disabledReason={!modalName.trim() ? 'Name is required' : undefined}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="font-semibold">Name</label>
                    <LemonInput placeholder="e.g. Experiments" value={modalName} onChange={setModalName} autoFocus />
                </div>
                <div>
                    <label className="font-semibold">Team</label>
                    <LemonSelect
                        options={roleOptions}
                        value={modalRoleId}
                        onChange={setModalRoleId}
                        placeholder="Select a team"
                        fullWidth
                        disabledReason={
                            !hasRolesFeature ? 'Role-based access requires an enterprise license' : undefined
                        }
                    />
                </div>
            </div>
        </LemonModal>
    )
}
