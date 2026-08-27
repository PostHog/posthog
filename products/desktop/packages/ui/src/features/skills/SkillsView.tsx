import {
  CaretDownIcon,
  Lightbulb,
  MagnifyingGlass,
  Plus,
} from "@phosphor-icons/react";
import { analyzeSkills } from "@posthog/core/skills/analyzeSkills";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@posthog/quill";
import {
  PI_HARNESS_FLAG,
  type SkillInfo,
  type SkillSource,
} from "@posthog/shared";
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
import type { AgentFlowModelOption } from "../agent-flows/AgentFlowEditor";
import {
  FlowEditorPanel,
  type FlowEditorState,
} from "../agent-flows/FlowEditorPanel";
import { FlowSkillCard } from "../agent-flows/FlowSkillCard";
import { useAgentFlows } from "../agent-flows/useAgentFlows";
import { useFeatureFlag } from "../feature-flags/useFeatureFlag";
import { usePiModelCatalog } from "../pi-sessions/usePiModelCatalog";
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
  const [sourceFilter, setSourceFilter] = useState<SkillSource | "all">("all");
  const [newSkillOpen, setNewSkillOpen] = useState(false);
  const [flowEditor, setFlowEditor] = useState<FlowEditorState | null>(null);

  const flowsEnabled = useFeatureFlag(PI_HARNESS_FLAG, import.meta.env.DEV);
  const { flows } = useAgentFlows();
  const flowModelQuery = usePiModelCatalog(flowsEnabled);
  const flowModels = (flowModelQuery.data ?? []) as AgentFlowModelOption[];
  const flowPaths = useMemo(
    () => new Set(flows.map((flow) => flow.skillPath)),
    [flows],
  );
  const visibleFlows = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return flows;
    return flows.filter((flow) => flow.name.toLowerCase().includes(query));
  }, [flows, searchQuery]);

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
    setFlowEditor(null);
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
      if (flowPaths.has(skill.path)) {
        continue;
      }
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
  }, [skills, searchQuery, flowPaths]);

  const sourceCounts = useMemo(() => {
    const counts = new Map<SkillSource, number>();
    for (const [source, items] of grouped) {
      counts.set(source, items.length);
    }
    return counts;
  }, [grouped]);

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
          <Box flexGrow="1" className="flex min-w-0 flex-col">
            <Box className="shrink-0 border-b border-b-(--gray-4)">
              <Box px="4" pt="3" className="mx-auto w-full max-w-5xl">
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
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={
                        <Button size="2" variant="soft">
                          <Plus size={14} />
                          New
                          <CaretDownIcon size={10} />
                        </Button>
                      }
                    />
                    <DropdownMenuContent align="end" className="min-w-[260px]">
                      <DropdownMenuItem onClick={() => setNewSkillOpen(true)}>
                        Blank skill
                      </DropdownMenuItem>
                      {flowsEnabled ? (
                        <DropdownMenuItem
                          disabled={flowModels.length === 0}
                          onClick={() =>
                            setFlowEditor({
                              key: crypto.randomUUID(),
                              name: "",
                              roles: ["planner", "executor"],
                            })
                          }
                        >
                          Agent flow
                        </DropdownMenuItem>
                      ) : null}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </Flex>
                <Flex gap="1" pb="3" className="flex-wrap">
                  {(
                    [
                      ["all", "All"] as const,
                      ...SOURCE_ORDER.filter(
                        (source) => (sourceCounts.get(source) ?? 0) > 0,
                      ).map(
                        (source) =>
                          [source, SOURCE_CONFIG[source].sectionTitle] as const,
                      ),
                    ] as Array<[SkillSource | "all", string]>
                  ).map(([value, label]) => {
                    const isActive = sourceFilter === value;
                    const count =
                      value === "all"
                        ? (visibleFlows.length ? visibleFlows.length : 0) +
                          [...sourceCounts.values()].reduce(
                            (sum, item) => sum + item,
                            0,
                          )
                        : (sourceCounts.get(value) ?? 0);
                    return (
                      <button
                        key={value}
                        type="button"
                        className={`rounded-full border px-2.5 py-1 text-[12px] transition-colors ${
                          isActive
                            ? "border-accent-8 bg-accent-3 text-accent-11"
                            : "border-gray-5 bg-gray-1 text-gray-11 hover:bg-gray-3"
                        }`}
                        onClick={() => setSourceFilter(value)}
                      >
                        {label}
                        <span
                          className={`ml-1 ${isActive ? "text-accent-10" : "text-gray-8"}`}
                        >
                          {count}
                        </span>
                      </button>
                    );
                  })}
                </Flex>
              </Box>
            </Box>
            <ScrollArea
              type="auto"
              className="scroll-area-constrain-width min-h-0 flex-1"
            >
              <Box px="4" pb="3" className="mx-auto w-full max-w-5xl">
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
                    {(sourceFilter === "all"
                      ? [...sourceCounts.values()].reduce(
                          (sum, item) => sum + item,
                          0,
                        ) + visibleFlows.length
                      : (sourceCounts.get(sourceFilter) ?? 0)) === 0 ? (
                      <Flex
                        direction="column"
                        align="center"
                        gap="2"
                        className="rounded-lg border border-gray-5 border-dashed py-8"
                      >
                        <Text className="text-[13px] text-gray-10">
                          No skills match your search.
                        </Text>
                        <Button
                          size="1"
                          variant="soft"
                          onClick={() => {
                            setSearchQuery("");
                            setSourceFilter("all");
                          }}
                        >
                          Clear search and filters
                        </Button>
                      </Flex>
                    ) : null}
                    {flowsEnabled &&
                    visibleFlows.length > 0 &&
                    (sourceFilter === "all" || sourceFilter === "user") ? (
                      <Flex direction="column" gap="1">
                        <Flex align="center" gap="2" className="mb-1">
                          <Text className="font-medium text-[12px] text-gray-9 uppercase tracking-wider">
                            Flows
                          </Text>
                          <Text className="text-[11px] text-gray-8">
                            {visibleFlows.length}
                          </Text>
                        </Flex>
                        <Flex direction="column" gap="1">
                          {visibleFlows.map((flow) => (
                            <FlowSkillCard
                              key={flow.skillPath}
                              flow={flow}
                              onClick={() => {
                                setSelectedPath(null);
                                setFlowEditor({
                                  key: crypto.randomUUID(),
                                  flow,
                                  name: flow.name,
                                  roles: flow.steps.map((step) => step.role),
                                });
                              }}
                            />
                          ))}
                        </Flex>
                      </Flex>
                    ) : null}
                    {SOURCE_ORDER.map((source) => {
                      if (sourceFilter !== "all" && sourceFilter !== source) {
                        return null;
                      }
                      const items = grouped.get(source);
                      if (!items || items.length === 0) return null;
                      const config = SOURCE_CONFIG[source];

                      return (
                        <SkillSection
                          key={source}
                          hideHeader={sourceFilter === source}
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
            open={!!selectedSkill || !!flowEditor}
            width={sidebarWidth}
            setWidth={setSidebarWidth}
            isResizing={isResizing}
            setIsResizing={setIsResizing}
            side="right"
          >
            {flowEditor ? (
              <FlowEditorPanel
                key={flowEditor.key}
                state={flowEditor}
                models={flowModels}
                canPublish={!!teamListing?.available}
                onClose={() => setFlowEditor(null)}
                onOpenFiles={(skillPath) => {
                  setFlowEditor(null);
                  setSelectedPath(skillPath);
                  setScrollToPath(skillPath);
                }}
              />
            ) : selectedSkill ? (
              <SkillDetailPanel
                key={selectedSkill.path}
                skill={selectedSkill}
                issues={analysis[selectedSkill.path] ?? []}
                canPublish={!!teamListing?.available}
                onClose={handleCloseSidebar}
              />
            ) : null}
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
