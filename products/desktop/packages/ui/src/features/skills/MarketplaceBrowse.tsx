import { DownloadSimpleIcon, StorefrontIcon } from "@phosphor-icons/react";
import { useDebouncedValue } from "@posthog/ui/primitives/hooks/useDebouncedValue";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { useState } from "react";
import { MarketplaceSkillPanel } from "./MarketplaceSkillPanel";
import { SkillListCard } from "./SkillListCard";
import { SkillChip } from "./SkillPanelHeader";
import { SkillListSkeleton } from "./SkillSkeletons";
import { SkillsToolbar } from "./SkillsToolbar";
import { useSkillsSidebarStore } from "./skillsSidebarStore";
import {
  installsFormatter,
  type MarketplaceSkillSummary,
  useMarketplacePopular,
  useMarketplaceSearch,
} from "./useMarketplace";

export function MarketplaceBrowse() {
  const [query, setQuery] = useState("");
  const { debounced: debouncedQuery } = useDebouncedValue(query, 300);
  const [selected, setSelected] = useState<MarketplaceSkillSummary | null>(
    null,
  );

  const isSearching = debouncedQuery.trim().length >= 2;
  const search = useMarketplaceSearch(debouncedQuery);
  const popular = useMarketplacePopular(!isSearching);
  const active = isSearching ? search : popular;
  const results = active.data?.results ?? [];

  const {
    width: sidebarWidth,
    setWidth: setSidebarWidth,
    isResizing,
    setIsResizing,
  } = useSkillsSidebarStore();

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <SkillsToolbar
          placeholder="Search community skills"
          value={query}
          onChange={setQuery}
        />

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-5xl px-4 py-3">
            {active.error ? (
              <BrowseEmptyState message="Could not reach the skills index. Check your connection and try again." />
            ) : active.isLoading ? (
              <SkillListSkeleton rows={6} />
            ) : results.length === 0 ? (
              <BrowseEmptyState message="No skills found" />
            ) : (
              <div className="flex flex-col gap-0.5">
                {isSearching ? null : (
                  <p className="pb-1 font-medium text-[12px] text-gray-9 uppercase tracking-wider">
                    Most installed
                  </p>
                )}
                {results.map((result) => (
                  <SkillListCard
                    key={result.id}
                    icon={<StorefrontIcon size={12} weight="duotone" />}
                    title={result.name}
                    subtitle={result.source}
                    isSelected={selected?.id === result.id}
                    onClick={() =>
                      setSelected((prev) =>
                        prev?.id === result.id ? null : result,
                      )
                    }
                    trailing={
                      <>
                        {result.installed && (
                          <SkillChip tone="positive">Installed</SkillChip>
                        )}
                        <span
                          className="flex shrink-0 items-center gap-1 text-[11px] text-gray-9 tabular-nums"
                          title={`${installsFormatter.format(result.installs)} installs`}
                        >
                          <DownloadSimpleIcon size={12} />
                          {installsFormatter.format(result.installs)}
                        </span>
                      </>
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <ResizableSidebar
        open={!!selected}
        width={sidebarWidth}
        setWidth={setSidebarWidth}
        isResizing={isResizing}
        setIsResizing={setIsResizing}
        side="right"
      >
        {selected && (
          <MarketplaceSkillPanel
            key={selected.id}
            result={selected}
            onClose={() => setSelected(null)}
          />
        )}
      </ResizableSidebar>
    </div>
  );
}

function BrowseEmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12">
      <div className="rounded-lg border border-gray-6 border-dashed p-4">
        <StorefrontIcon size={24} className="text-gray-8" />
      </div>
      <p className="max-w-[360px] text-center text-[13px] text-gray-10">
        {message}
      </p>
    </div>
  );
}
