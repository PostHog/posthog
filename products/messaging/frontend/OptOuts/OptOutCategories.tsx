import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton, LemonCollapse, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'
import { IconPlusSmall, IconGear } from '@posthog/icons'
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
    const [isNewCategoryModalOpen, setIsNewCategoryModalOpen] = React.useState(false)
    const [editingCategory, setEditingCategory] = React.useState<MessageCategory | null>(null)

    React.useEffect(() => {
        loadCategories()
    }, [loadCategories])

    const handleEditCategory = (category: MessageCategory): void => {
        setEditingCategory(category)
    }

    const handleCloseModal = (): void => {
        setIsNewCategoryModalOpen(false)
        setEditingCategory(null)
    }

    const collapseItems = (categories || []).map((category: MessageCategory) => ({
        key: category.id,
        header: (
            <div className="flex items-center justify-between w-full">
                <div>
                    <div className="font-medium">{category.name}</div>
                    <div className="text-xs text-muted">{category.description}</div>
                </div>
                <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    <LemonTag type={category.category_type === 'marketing' ? 'success' : 'completion'}>
                        {capitalizeFirstLetter(category.category_type)}
                    </LemonTag>
                    <LemonButton icon={<IconGear />} size="small" onClick={() => handleEditCategory(category)}>
                        Edit
                    </LemonButton>
                    <LemonButton size="small" status="danger" onClick={() => deleteCategory(category.id)}>
                        Delete
                    </LemonButton>
                </div>
            </div>
        ),
        content: (
            <div>
                <div className="mb-3">
                    <div className="text-sm text-muted mb-1">Key: {category.key}</div>
                    {category.public_description && (
                        <div className="text-sm text-muted">Public description: {category.public_description}</div>
                    )}
                </div>
                <div>
                    <h4 className="font-medium mb-2">Opt-out list</h4>
                    <OptOutList categoryName={category.name} />
                </div>
            </div>
        ),
    }))

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
