import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import * as construction2Png from '@posthog/brand/hoggies/png/construction-2'
import { IconDownload, IconPlus } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonDialog, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { customerIOImportLogic } from './customerIOImportLogic'
import { NewCategoryModal } from './NewCategoryModal'
import { MessageCategory, optOutCategoriesLogic } from './optOutCategoriesLogic'
import { OptOutList } from './OptOutList'
import { topicVocabularyLogic } from './topicVocabularyLogic'

const HedgehogConstruction2 = pngHoggie(construction2Png)

function CategorySummary({ category }: { category: MessageCategory }): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <div>
                <div className="font-medium">{category.name}</div>
                <div className="text-xs text-muted">{category.description}</div>
            </div>
            <LemonTag type={category.category_type === 'marketing' ? 'success' : 'completion'}>
                {(category.category_type ?? '').toUpperCase()}
            </LemonTag>
        </div>
    )
}

function TopicSummary({ category }: { category: MessageCategory }): JSX.Element {
    const isMarketing = category.category_type === 'marketing'
    return (
        <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 min-w-0">
                <span className="font-medium min-w-0 break-words">{category.name}</span>
                <code className="text-xs text-muted font-normal min-w-0 break-all">{category.key}</code>
                <LemonTag type={isMarketing ? 'success' : 'completion'} size="small">
                    {isMarketing ? 'Marketing' : 'Transactional'}
                </LemonTag>
            </div>
            <div className="text-xs text-muted">{category.description}</div>
        </div>
    )
}

export function OptOutCategories(): JSX.Element {
    const { categories, categoriesLoading, isNewCategoryModalOpen } = useValues(optOutCategoriesLogic)
    const { loadCategories, deleteCategory, closeNewCategoryModal, openNewCategoryModal } =
        useActions(optOutCategoriesLogic)
    const { openImportModal } = useActions(customerIOImportLogic)
    const { words, speaksAudience } = useValues(topicVocabularyLogic)
    const [editingCategory, setEditingCategory] = useState<MessageCategory | null>(null)

    useEffect(() => {
        loadCategories()
    }, [loadCategories])

    const handleEditCategory = (category: MessageCategory): void => {
        setEditingCategory(category)
    }

    const handleCloseModal = (): void => {
        setEditingCategory(null)
    }

    const collapseItems = useMemo(
        () =>
            (categories || []).map((category: MessageCategory) => ({
                key: category.id,
                header: (
                    <div className="flex justify-between w-full gap-2">
                        {speaksAudience ? (
                            <TopicSummary category={category} />
                        ) : (
                            <CategorySummary category={category} />
                        )}
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
                                                title: words.topics.deleteTitle,
                                                description: (
                                                    <>
                                                        <p>
                                                            {words.topics.deleteQuestion} <b>{category.name}</b>?
                                                        </p>
                                                        <p>{words.topics.deleteConsequence}</p>
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
                            {!speaksAudience && <div className="text-sm text-muted mb-1">Key: {category.key}</div>}
                            {category.public_description && (
                                <div className="text-sm text-muted">
                                    Public description: {category.public_description}
                                </div>
                            )}
                        </div>
                        <div>
                            <h4 className="font-medium mb-4">{words.topics.unsubscribedHeading}</h4>
                            {category.category_type === 'marketing' ? (
                                <OptOutList category={category} />
                            ) : (
                                <div className="text-sm text-muted mb-1">{words.topics.transactionalNotice}</div>
                            )}
                        </div>
                    </div>
                ),
            })),
        [categories, deleteCategory, words, speaksAudience]
    )

    return (
        <>
            {categoriesLoading ? (
                <LemonSkeleton className="h-10" />
            ) : (
                <>
                    {collapseItems.length > 0 ? (
                        <LemonCollapse panels={collapseItems} />
                    ) : (
                        <ProductIntroduction
                            thingName={words.topics.emptyStateThing}
                            description={words.topics.emptyStateDescription}
                            docsURL="https://posthog.com/docs/workflows/customerio-import"
                            actionElementOverride={
                                speaksAudience ? undefined : (
                                    <>
                                        <LemonButton type="primary" icon={<IconDownload />} onClick={openImportModal}>
                                            Import from Customer.io
                                        </LemonButton>
                                        <LemonButton
                                            type="secondary"
                                            icon={<IconPlus />}
                                            onClick={openNewCategoryModal}
                                        >
                                            Create category
                                        </LemonButton>
                                    </>
                                )
                            }
                            customHog={HedgehogConstruction2}
                            isEmpty
                        />
                    )}
                </>
            )}

            <NewCategoryModal
                isOpen={isNewCategoryModalOpen || editingCategory !== null}
                onClose={() => {
                    closeNewCategoryModal()
                    handleCloseModal()
                }}
                category={editingCategory}
            />
        </>
    )
}
