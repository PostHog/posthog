import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCopy, IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTag, Spinner } from '@posthog/lemon-ui'

import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { CACHE_LABELS, featureFlagsStaffToolsLogic } from './featureFlagsStaffToolsLogic'

const SEARCH_DEBOUNCE_MS = 300

export function StaffCacheEntryModal(): JSX.Element {
    const { viewingCacheEntry, cacheEntry, cacheEntryLoading } = useValues(featureFlagsStaffToolsLogic)
    const { closeCacheEntryModal } = useActions(featureFlagsStaffToolsLogic)

    const [searchValue, setSearchValue] = useState('')
    const searchQuery = useDebouncedValue(searchValue, SEARCH_DEBOUNCE_MS)

    // Clear the search whenever a different entry is opened (or the modal closes).
    useEffect(() => {
        setSearchValue('')
    }, [viewingCacheEntry?.teamId, viewingCacheEntry?.cache])

    return (
        <LemonModal
            title={
                viewingCacheEntry ? `${CACHE_LABELS[viewingCacheEntry.cache]} — team #${viewingCacheEntry.teamId}` : ''
            }
            isOpen={!!viewingCacheEntry}
            onClose={closeCacheEntryModal}
            width={720}
        >
            {!cacheEntryLoading && cacheEntry?.data ? (
                <div className="flex items-center gap-2 mb-2">
                    <LemonInput
                        placeholder="Search…"
                        prefix={<IconSearch />}
                        value={searchValue}
                        onChange={setSearchValue}
                        size="small"
                        className="flex-1"
                        data-attr="staff-cache-entry-search"
                    />
                    <LemonButton
                        icon={<IconCopy />}
                        size="small"
                        onClick={() => void copyToClipboard(JSON.stringify(cacheEntry.data, null, 2), 'cache entry')}
                    >
                        Copy
                    </LemonButton>
                </div>
            ) : null}
            <div className="max-h-[70vh] overflow-y-auto">
                {cacheEntryLoading ? (
                    <div className="flex items-center justify-center p-8">
                        <Spinner className="text-2xl" />
                    </div>
                ) : cacheEntry?.data ? (
                    <HighlightedJSONViewer
                        src={cacheEntry.data}
                        name={null}
                        collapsed={2}
                        sortKeys={true}
                        searchQuery={searchQuery}
                    />
                ) : (
                    <div className="flex items-center gap-2 p-4">
                        <LemonTag type="warning">Miss</LemonTag>
                        <span className="text-secondary">Nothing is cached in Redis for this team.</span>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
