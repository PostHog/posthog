import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { ProductAreaType, RoleType } from '~/types'

import type { productAreasLogicType } from './productAreasLogicType'

export const productAreasLogic = kea<productAreasLogicType>([
    path(['products', 'earlyAccessFeatures', 'frontend', 'productAreasLogic']),

    actions({
        openModal: (productArea?: ProductAreaType) => ({ productArea }),
        closeModal: true,
        setModalName: (name: string) => ({ name }),
        setModalRoleId: (roleId: string | null) => ({ roleId }),
        saveProductArea: true,
    }),

    loaders({
        productAreas: {
            __default: [] as ProductAreaType[],
            loadProductAreas: async () => {
                const response = await api.productAreas.list()
                return response.results
            },
            deleteProductArea: async (id: string) => {
                await api.productAreas.delete(id)
                const response = await api.productAreas.list()
                return response.results
            },
        },
        roles: {
            __default: [] as RoleType[],
            loadRoles: async () => {
                const response = await api.roles.list()
                return response?.results || []
            },
        },
    }),

    reducers({
        isModalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        editingProductArea: [
            null as ProductAreaType | null,
            {
                openModal: (_, { productArea }) => productArea ?? null,
                closeModal: () => null,
            },
        ],
        modalName: [
            '',
            {
                openModal: (_, { productArea }) => productArea?.name ?? '',
                closeModal: () => '',
                setModalName: (_, { name }) => name,
            },
        ],
        modalRoleId: [
            null as string | null,
            {
                openModal: (_, { productArea }) => productArea?.role_id ?? null,
                closeModal: () => null,
                setModalRoleId: (_, { roleId }) => roleId,
            },
        ],
        isSaving: [
            false,
            {
                saveProductArea: () => true,
                closeModal: () => false,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        saveProductArea: async () => {
            const { editingProductArea, modalName, modalRoleId } = values
            const data = { name: modalName, role_id: modalRoleId }
            if (editingProductArea) {
                await api.productAreas.update(editingProductArea.id, data)
            } else {
                await api.productAreas.create(data)
            }
            actions.loadProductAreas()
            actions.closeModal()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadProductAreas()
        actions.loadRoles()
    }),
])
