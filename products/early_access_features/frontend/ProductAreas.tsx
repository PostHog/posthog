import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonTable } from '@posthog/lemon-ui'

import { ProductAreaType } from '~/types'

import { productAreasLogic } from './productAreasLogic'

export function ProductAreas(): JSX.Element {
    const { productAreas, productAreasLoading, roles } = useValues(productAreasLogic)
    const { deleteProductArea, openModal } = useActions(productAreasLogic)

    const confirmDelete = (productArea: ProductAreaType): void => {
        LemonDialog.open({
            title: 'Delete product area?',
            description: `Are you sure you want to delete "${productArea.name}"? This action cannot be undone.`,
            primaryButton: {
                children: 'Delete',
                type: 'primary',
                status: 'danger',
                onClick: () => deleteProductArea(productArea.id),
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
            },
        })
    }
    const isEmpty = productAreas.length === 0 && !productAreasLoading

    const getRoleName = (roleId: string | null): string => {
        if (!roleId) {
            return '-'
        }
        const role = roles.find((r) => r.id === roleId)
        return role?.name ?? '-'
    }

    return (
        <>
            {isEmpty ? (
                <div className="border border-dashed rounded p-6 text-center">
                    <h3 className="mt-0">No product areas yet</h3>
                    <p className="text-muted">
                        Product areas help you organize features by team or domain. Create your first product area to
                        get started.
                    </p>
                    <LemonButton type="primary" onClick={() => openModal()}>
                        New product area
                    </LemonButton>
                </div>
            ) : (
                <LemonTable<ProductAreaType>
                    loading={productAreasLoading}
                    columns={[
                        {
                            title: 'Name',
                            key: 'name',
                            render(_, productArea) {
                                return (
                                    <span
                                        className="cursor-pointer font-semibold"
                                        onClick={() => openModal(productArea)}
                                    >
                                        {productArea.name}
                                    </span>
                                )
                            },
                            sorter: (a, b) => a.name.localeCompare(b.name),
                        },
                        {
                            title: 'Team',
                            key: 'team',
                            render(_, productArea) {
                                return getRoleName(productArea.role_id)
                            },
                        },
                        {
                            title: 'Created',
                            dataIndex: 'created_at',
                            render(_, { created_at }) {
                                return new Date(created_at).toLocaleDateString()
                            },
                            sorter: (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
                        },
                        {
                            title: '',
                            key: 'actions',
                            width: 0,
                            render(_, productArea) {
                                return (
                                    <LemonButton
                                        size="small"
                                        status="danger"
                                        onClick={() => confirmDelete(productArea)}
                                    >
                                        Delete
                                    </LemonButton>
                                )
                            },
                        },
                    ]}
                    dataSource={productAreas}
                />
            )}
        </>
    )
}
