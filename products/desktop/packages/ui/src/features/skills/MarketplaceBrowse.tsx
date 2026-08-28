import { MagnifyingGlass, Storefront } from "@phosphor-icons/react";
import { useDebouncedValue } from "@posthog/ui/primitives/hooks/useDebouncedValue";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import {
  Badge,
  Box,
  Flex,
  ScrollArea,
  Text,
  TextField,
} from "@radix-ui/themes";
import { useState } from "react";
import { MarketplaceSkillPanel } from "./MarketplaceSkillPanel";
import { SkillListCard } from "./SkillListCard";
import { useSkillsSidebarStore } from "./skillsSidebarStore";
import {
  installsFormatter,
  type MarketplaceSkillSummary,
  useMarketplaceSearch,
} from "./useMarketplace";

export function MarketplaceBrowse() {
  const [query, setQuery] = useState("");
  const { debounced: debouncedQuery } = useDebouncedValue(query, 300);
  const [selected, setSelected] = useState<MarketplaceSkillSummary | null>(
    null,
  );

  const { data, isLoading, error } = useMarketplaceSearch(debouncedQuery);
  const results = data?.results ?? [];

  const {
    width: sidebarWidth,
    setWidth: setSidebarWidth,
    isResizing,
    setIsResizing,
  } = useSkillsSidebarStore();

  return (
    <Flex className="min-h-0 flex-1">
      <Box flexGrow="1" className="min-w-0">
        <ScrollArea type="auto" className="scroll-area-constrain-width h-full">
          <Box px="4" py="3">
            <Box pb="3">
              <TextField.Root
                size="2"
                placeholder="Search community skills..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="text-[13px]"
              >
                <TextField.Slot>
                  <MagnifyingGlass size={14} />
                </TextField.Slot>
              </TextField.Root>
            </Box>

            {debouncedQuery.trim().length < 2 ? (
              <BrowseEmptyState message="Search the community skills index from skills.sh" />
            ) : error ? (
              <BrowseEmptyState message="Could not reach the skills index. Check your connection and try again." />
            ) : isLoading ? (
              <Text className="text-[12px] text-gray-9">Searching...</Text>
            ) : results.length === 0 ? (
              <BrowseEmptyState message="No skills found" />
            ) : (
              <Flex direction="column" gap="1">
                {results.map((result) => (
                  <SkillListCard
                    key={result.id}
                    icon={
                      <Storefront
                        size={14}
                        weight="duotone"
                        className="text-gray-11"
                      />
                    }
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
                          <Badge
                            size="1"
                            variant="soft"
                            color="green"
                            className="shrink-0"
                          >
                            Installed
                          </Badge>
                        )}
                        <Text className="shrink-0 text-[12px] text-gray-9 tabular-nums">
                          {installsFormatter.format(result.installs)}
                        </Text>
                      </>
                    }
                  />
                ))}
              </Flex>
            )}
          </Box>
        </ScrollArea>
      </Box>

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
    </Flex>
  );
}

function BrowseEmptyState({ message }: { message: string }) {
  return (
    <Flex
      align="center"
      justify="center"
      direction="column"
      gap="3"
      className="py-12"
    >
      <Box className="rounded-lg border border-gray-6 border-dashed p-4">
        <Storefront size={24} className="text-gray-8" />
      </Box>
      <Text className="max-w-[360px] text-center text-[13px] text-gray-10">
        {message}
      </Text>
    </Flex>
  );
}
