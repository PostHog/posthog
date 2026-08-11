import { Lightbulb, MagnifyingGlass, Plus } from "@phosphor-icons/react";
import { analyzeSkills } from "@posthog/core/skills/analyzeSkills";
import { Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import type { SkillInfo, SkillSource } from "@posthog/shared";
import {
  Box,
  Button,
  Flex,
  ScrollArea,
  Text,
  TextField,
} from "@radix-ui/themes";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ResizableSidebar } from "../../primitives/ResizableSidebar";
import { MarketplaceBrowse } from "./MarketplaceBrowse";
import { NewSkillDialog } from "./NewSkillDialog";
import { SkillSection, SOURCE_CONFIG } from "./SkillCard";
import { SkillDetailPanel } from "./SkillDetailPanel";
import {
  useRequestedSkillName,
  useSkillsSelectionActions,
} from "./skillsSelectionStore";
import { useSkillsSidebarStore } from "./skillsSidebarStore";
import { TeamSkillsTab } from "./TeamSkillsTab";
import { useSkills } from "./useSkills";
import { useSkillsWatcher } from "./useSkillsWatcher";
import { useTeamSkills } from "./useTeamSkills";

const SOURCE_ORDER: SkillSource[] = [
  "user",
  "marketplace",
  "repo",
  "codex",
  "bundled",
];

// Installed = on disk, usable by agents right now. Team and Marketplace are
// remote catalogs; installing materializes a skill into Installed.
type SkillsTab = "installed" | "team" | "marketplace";

export function SkillsView() {
  const { data: skills = [], isLoading } = useSkills();
  useSkillsWatcher();

  const [tab, setTab] = useState<SkillsTab>("installed");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [scrollToPath, setScrollToPath] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [newSkillOpen, setNewSkillOpen] = useState(false);

  const { data: teamListing } = useTeamSkills(skills);
  const teamAvailable = teamListing?.available ?? false;
  // Team access revoked mid-session: fall back to Installed.
  const activeTab: SkillsTab =
    tab === "team" && !teamAvailable ? "installed" : tab;

  const {
    width: sidebarWidth,
    setWidth: setSidebarWidth,
    isResizing,
    setIsResizing,
  } = useSkillsSidebarStore();

  const selectedSkill = useMemo(() => {
    if (selectedPath === null || skills.length === 0) return null;
    return skills.find((s) => s.path === selectedPath) ?? null;
  }, [skills, selectedPath]);

  const handleSelect = useCallback((path: string) => {
    setSelectedPath((prev) => (prev === path ? null : path));
  }, []);

  // Another surface (e.g. the scout helper links) can ask to open a specific
  // skill by name; honor it once the skill list has loaded, then clear it.
  const requestedSkillName = useRequestedSkillName();
  const { clearRequestedSkill } = useSkillsSelectionActions();
  useEffect(() => {
    if (!requestedSkillName || skills.length === 0) return;
    const match = skills.find((s) => s.name === requestedSkillName);
    if (match) {
      setSelectedPath(match.path);
      setScrollToPath(match.path);
    }
    clearRequestedSkill();
  }, [requestedSkillName, skills, clearRequestedSkill]);

  const handleScrolledIntoView = useCallback(() => setScrollToPath(null), []);

  const handleCloseSidebar = useCallback(() => {
    setSelectedPath(null);
  }, []);

  const analysis = useMemo(() => analyzeSkills(skills), [skills]);

  const grouped = useMemo(() => {
    const map = new Map<SkillSource, SkillInfo[]>();
    for (const source of SOURCE_ORDER) {
      map.set(source, []);
    }
    const query = searchQuery.trim().toLowerCase();
    for (const skill of skills) {
      if (
        query &&
        !skill.name.toLowerCase().includes(query) &&
        !(skill.description?.toLowerCase().includes(query) ?? false)
      ) {
        continue;
      }
      const list = map.get(skill.source);
      if (list) {
        list.push(skill);
      }
    }
    return map;
  }, [skills, searchQuery]);

  return (
    <Flex direction="column" height="100%" className="overflow-hidden">
      <Box px="4" className="shrink-0 border-b border-b-(--gray-5)">
        <Tabs
          value={activeTab}
          onValueChange={(value: string) => setTab(value as SkillsTab)}
        >
          <TabsList variant="line" className="h-auto gap-0.5">
            <TabsTrigger value="installed" className="gap-1.5 px-2.5 py-2">
              <span className="font-medium text-[13px]">Installed</span>
            </TabsTrigger>
            {teamAvailable && (
              <TabsTrigger value="team" className="gap-1.5 px-2.5 py-2">
                <span className="font-medium text-[13px]">Team</span>
              </TabsTrigger>
            )}
            <TabsTrigger value="marketplace" className="gap-1.5 px-2.5 py-2">
              <span className="font-medium text-[13px]">Marketplace</span>
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </Box>

      {activeTab === "marketplace" ? (
        <MarketplaceBrowse />
      ) : activeTab === "team" ? (
        <TeamSkillsTab skills={teamListing?.skills ?? []} />
      ) : (
        <Flex className="min-h-0 flex-1">
          <Box flexGrow="1" className="min-w-0">
            <ScrollArea
              type="auto"
              className="scroll-area-constrain-width h-full"
            >
              <Box px="4" py="3">
                <Flex pb="3" gap="2" align="center">
                  <Box flexGrow="1">
                    <TextField.Root
                      size="2"
                      placeholder="Search skills..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="text-[13px]"
                    >
                      <TextField.Slot>
                        <MagnifyingGlass size={14} />
                      </TextField.Slot>
                    </TextField.Root>
                  </Box>
                  <Button
                    size="2"
                    variant="soft"
                    onClick={() => setNewSkillOpen(true)}
                  >
                    <Plus size={14} />
                    New skill
                  </Button>
                </Flex>
                {skills.length === 0 && !isLoading ? (
                  <Flex
                    align="center"
                    justify="center"
                    direction="column"
                    gap="3"
                    className="py-12"
                  >
                    <Box className="rounded-lg border border-gray-6 border-dashed p-4">
                      <Lightbulb size={24} className="text-gray-8" />
                    </Box>
                    <Text className="text-[13px] text-gray-10">
                      No skills found
                    </Text>
                  </Flex>
                ) : (
                  <Flex direction="column" gap="5">
                    {SOURCE_ORDER.map((source) => {
                      const items = grouped.get(source);
                      if (!items || items.length === 0) return null;
                      const config = SOURCE_CONFIG[source];

                      return (
                        <SkillSection
                          key={source}
                          title={config.sectionTitle}
                          skills={items}
                          selectedPath={selectedSkill?.path ?? null}
                          onSelect={handleSelect}
                          scrollToPath={scrollToPath}
                          onScrolledIntoView={handleScrolledIntoView}
                          analysis={analysis}
                        />
                      );
                    })}
                  </Flex>
                )}
              </Box>
            </ScrollArea>
          </Box>

          <ResizableSidebar
            open={!!selectedSkill}
            width={sidebarWidth}
            setWidth={setSidebarWidth}
            isResizing={isResizing}
            setIsResizing={setIsResizing}
            side="right"
          >
            {selectedSkill && (
              <SkillDetailPanel
                key={selectedSkill.path}
                skill={selectedSkill}
                issues={analysis[selectedSkill.path] ?? []}
                canPublish={!!teamListing?.available}
                onClose={handleCloseSidebar}
              />
            )}
          </ResizableSidebar>
        </Flex>
      )}

      <NewSkillDialog
        open={newSkillOpen}
        onOpenChange={setNewSkillOpen}
        onCreated={(path) => setSelectedPath(path)}
      />
    </Flex>
  );
}
