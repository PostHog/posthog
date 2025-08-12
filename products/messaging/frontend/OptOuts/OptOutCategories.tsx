import { useEffect, useMemo, useState } from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton, LemonCollapse, LemonDialog, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'
import { IconPlusSmall } from '@posthog/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { useActions, useValues } from 'kea'
import { optOutCategoriesLogic } from './optOutCategoriesLogic'
import { OptOutList } from './OptOutList'
import { NewCategoryModal } from './NewCategoryModal'
import { capitalizeFirstLetter } from 'lib/utils'

interface MessageCategory {
    id: string
    key: string
    name: string
    description: string
    public_description: string
    category_type: string
}

export function OptOutCategories(): JSX.Element {
    const { categories, categoriesLoading } = useValues(optOutCategoriesLogic)
    const { loadCategories, deleteCategory } = useActions(optOutCategoriesLogic)
    const [isNewCategoryModalOpen, setIsNewCategoryModalOpen] = useState(false)
    const [editingCategory, setEditingCategory] = useState<MessageCategory | null>(null)

    useEffect(() => {
        loadCategories()
    }, [loadCategories])

    const handleEditCategory = (category: MessageCategory): void => {
        setEditingCategory(category)
    }

    const handleCloseModal = (): void => {
        setIsNewCategoryModalOpen(false)
        setEditingCategory(null)
    }

    const collapseItems = useMemo(
        () =>
            (categories || []).map((category: MessageCategory) => ({
                key: category.id,
                header: (
                    <div className="flex justify-between w-full gap-2">
                        <div className="flex items-center gap-2">
                            <div>
                                <div className="font-medium">{category.name}</div>
                                <div className="text-xs text-muted">{category.description}</div>
                            </div>
                            <LemonTag type={category.category_type === 'marketing' ? 'success' : 'completion'}>
                                {capitalizeFirstLetter(category.category_type)}
                            </LemonTag>
                        </div>
                        <More
                            onClick={(e) => e.stopPropagation()}
                            overlay={
                                <>
                                    <LemonButton onClick={() => handleEditCategory(category)} fullWidth>
                                        Edit
                                    </LemonButton>
                                    <LemonDivider />
                                    <LemonButton
                                        status="danger"
                                        onClick={() =>
                                            LemonDialog.open({
                                                title: 'Delete category',
                                                description: (
                                                    <>
                                                        <p>
                                                            Are you sure you want to delete the message category{' '}
                                                            <b>{category.name}</b>?
                                                        </p>
                                                        <p>
                                                            All messages associated with this category must be updated
                                                            manually.
                                                        </p>
                                                    </>
                                                ),
                                                primaryButton: {
                                                    children: 'Delete',
                                                    status: 'danger',
                                                    onClick: () => deleteCategory(category.id),
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            })
                                        }
                                        fullWidth
                                    >
                                        Delete
                                    </LemonButton>
                                </>
                            }
                        />
                    </div>
                ),
                content: (
                    <div>
                        <div className="mb-3">
                            <div className="text-sm text-muted mb-1">Key: {category.key}</div>
                            {category.public_description && (
                                <div className="text-sm text-muted">
                                    Public description: {category.public_description}
                                </div>
                            )}
                        </div>
                        <div>
                            <h4 className="font-medium mb-2">Opt-out list</h4>
                            {category.category_type === 'marketing' ? (
                                <OptOutList category={category} />
                            ) : (
                                <div className="text-sm text-muted mb-1">
                                    Transactional messages are not eligible for opt-outs
                                </div>
                            )}
                        </div>
                    </div>
                ),
            })),
        [categories, deleteCategory]
    )

    return (
        <>
            <PageHeader
                caption="Configure message categories and view opt-outs"
                buttons={
                    <LemonButton
                        data-attr="new-optout-category"
                        icon={<IconPlusSmall />}
                        size="small"
                        type="primary"
                        onClick={() => setIsNewCategoryModalOpen(true)}
                    >
                        New category
                    </LemonButton>
                }
            />
            {categoriesLoading ? (
                <LemonSkeleton className="h-10" />
            ) : (
                <>
                    {collapseItems.length > 0 ? (
                        <LemonCollapse panels={collapseItems} />
                    ) : (
                        <div className="text-center py-8 text-muted">No message categories configured yet</div>
                    )}
                </>
            )}

            <NewCategoryModal
                isOpen={isNewCategoryModalOpen || editingCategory !== null}
                onClose={handleCloseModal}
                category={editingCategory}
            />
        </>
    )
}
