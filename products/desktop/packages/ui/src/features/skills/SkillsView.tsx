import {
  CaretDownIcon,
  CaretRightIcon,
  LightbulbIcon,
  PlusIcon,
} from "@phosphor-icons/react";
import { analyzeSkills } from "@posthog/core/skills/analyzeSkills";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Tabs,
  TabsList,
  TabsTrigger,
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import type { SkillInfo, SkillSource } from "@posthog/shared";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ResizableSidebar } from "../../primitives/ResizableSidebar";
import { MarketplaceBrowse } from "./MarketplaceBrowse";
import { NewSkillDialog } from "./NewSkillDialog";
import { SkillCard, SOURCE_CONFIG } from "./SkillCard";
import { SkillDetailPanel } from "./SkillDetailPanel";
import { SkillListSkeleton } from "./SkillSkeletons";
import { SkillsToolbar } from "./SkillsToolbar";
import {
  useRequestedSkillName,
  useSkillsSelectionActions,
} from "./skillsSelectionStore";
import { useSkillsSidebarStore } from "./skillsSidebarStore";
import { TeamSkillsTab } from "./TeamSkillsTab";
import { useMarketplacePopular } from "./useMarketplace";
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
type StatusFilter = "all" | "on" | "off";

interface SkillRow {
  path: string;
  skill: SkillInfo;
  showRepoBadge: boolean;
}

interface SkillsSection {
  key: string;
  title: string;
  rows: SkillRow[];
}

export function SkillsView() {
  const { data: skills = [], isLoading } = useSkills();
  useSkillsWatcher();

  const [tab, setTab] = useState<SkillsTab>("installed");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [scrollToPath, setScrollToPath] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SkillSource | "all">("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [collapsed, setCollapsed] = useState<string[]>([]);
  const [newSkillOpen, setNewSkillOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const { data: teamListing, isLoading: teamLoading } = useTeamSkills(skills);
  useMarketplacePopular(true);
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

  const matchedSkills = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return skills.filter((skill) => {
      if (statusFilter === "on" && skill.enabled === false) return false;
      if (statusFilter === "off" && skill.enabled !== false) return false;
      if (!query) return true;
      return (
        skill.name.toLowerCase().includes(query) ||
        (skill.description?.toLowerCase().includes(query) ?? false)
      );
    });
  }, [skills, searchQuery, statusFilter]);

  const sourceCounts = useMemo(() => {
    const counts = new Map<SkillSource, number>();
    for (const source of SOURCE_ORDER) {
      counts.set(
        source,
        matchedSkills.filter((skill) => skill.source === source).length,
      );
    }
    return counts;
  }, [matchedSkills]);

  const sections = useMemo<SkillsSection[]>(() => {
    const result: SkillsSection[] = [];
    for (const source of SOURCE_ORDER) {
      if (sourceFilter !== "all" && sourceFilter !== source) continue;
      const items = matchedSkills.filter((skill) => skill.source === source);
      if (items.length === 0) continue;
      const repoNames = new Set(
        items.map((skill) => skill.repoName).filter(Boolean),
      );
      const sharedRepo = repoNames.size === 1 ? [...repoNames][0] : undefined;
      result.push({
        key: source,
        title: sharedRepo
          ? `${SOURCE_CONFIG[source].sectionTitle} · ${sharedRepo}`
          : SOURCE_CONFIG[source].sectionTitle,
        rows: items.map((skill) => ({
          path: skill.path,
          skill,
          showRepoBadge: !sharedRepo,
        })),
      });
    }
    return result;
  }, [matchedSkills, sourceFilter]);

  const visibleRows = useMemo(
    () =>
      sections
        .filter((section) => !collapsed.includes(section.key))
        .flatMap((section) => section.rows),
    [sections, collapsed],
  );
  const totalRows = sections.reduce(
    (sum, section) => sum + section.rows.length,
    0,
  );

  useEffect(() => {
    if (activeTab !== "installed") return;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable;
      if (event.key === "/" && !typing) {
        event.preventDefault();
        searchRef.current?.focus();
        return;
      }
      if (typing) return;
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      if (visibleRows.length === 0) return;
      event.preventDefault();
      const current = visibleRows.findIndex((row) => row.path === selectedPath);
      const step = event.key === "ArrowDown" ? 1 : -1;
      const nextIndex =
        current === -1
          ? step === 1
            ? 0
            : visibleRows.length - 1
          : Math.min(Math.max(current + step, 0), visibleRows.length - 1);
      const next = visibleRows[nextIndex];
      setScrollToPath(next.path);
      setSelectedPath(next.path);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [activeTab, visibleRows, selectedPath]);

  const filterChips: Array<[SkillSource | "all", string, number]> = [
    [
      "all",
      "All",
      [...sourceCounts.values()].reduce((sum, item) => sum + item, 0),
    ],
    ...SOURCE_ORDER.filter((source) => (sourceCounts.get(source) ?? 0) > 0).map<
      [SkillSource, string, number]
    >((source) => [
      source,
      SOURCE_CONFIG[source].sectionTitle,
      sourceCounts.get(source) ?? 0,
    ]),
  ];

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="shrink-0 border-gray-5 border-b px-4">
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
      </div>

      {activeTab === "marketplace" ? (
        <MarketplaceBrowse />
      ) : activeTab === "team" ? (
        <TeamSkillsTab
          skills={teamListing?.skills ?? []}
          loading={teamLoading}
        />
      ) : (
        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            <SkillsToolbar
              placeholder="Search skills, or press /"
              value={searchQuery}
              onChange={setSearchQuery}
              inputRef={searchRef}
              actions={
                <>
                  <ToggleGroup
                    value={[statusFilter]}
                    onValueChange={(values: string[]) => {
                      const next = values[0];
                      if (next === "all" || next === "on" || next === "off") {
                        setStatusFilter(next);
                      }
                    }}
                    aria-label="Filter by state"
                    className="h-8 shrink-0"
                  >
                    <ToggleGroupItem value="all" className="h-8 px-2.5">
                      All
                    </ToggleGroupItem>
                    <ToggleGroupItem value="on" className="h-8 px-2.5">
                      On
                    </ToggleGroupItem>
                    <ToggleGroupItem value="off" className="h-8 px-2.5">
                      Off
                    </ToggleGroupItem>
                  </ToggleGroup>
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={
                        <Button
                          type="button"
                          variant="primary"
                          size="sm"
                          className="h-8"
                        >
                          <PlusIcon size={14} />
                          New
                        </Button>
                      }
                    />
                    <DropdownMenuContent align="end" className="min-w-[220px]">
                      <DropdownMenuItem onClick={() => setNewSkillOpen(true)}>
                        Blank skill
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </>
              }
              filters={filterChips.map(([value, label, count]) => {
                const isActive = sourceFilter === value;
                return (
                  <button
                    key={value}
                    type="button"
                    className={`rounded-full border px-2.5 py-0.5 text-[12px] transition-colors ${
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
            />

            <div className="ph-dotted-surface min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-5xl px-4 pb-3">
                {isLoading && skills.length === 0 ? (
                  <div className="pt-2">
                    <SkillListSkeleton />
                  </div>
                ) : skills.length === 0 ? (
                  <div className="flex flex-col items-center justify-center gap-3 py-12">
                    <div className="rounded-lg border border-gray-6 border-dashed p-4">
                      <LightbulbIcon size={24} className="text-gray-8" />
                    </div>
                    <p className="text-[13px] text-gray-10">No skills found</p>
                  </div>
                ) : totalRows === 0 ? (
                  <div className="mt-3 flex flex-col items-center gap-2 rounded-lg border border-gray-5 border-dashed py-8">
                    <p className="text-[13px] text-gray-10">
                      No skills match your search.
                    </p>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setSearchQuery("");
                        setSourceFilter("all");
                        setStatusFilter("all");
                      }}
                    >
                      Clear search and filters
                    </Button>
                  </div>
                ) : (
                  sections.map((section) => {
                    const isCollapsed = collapsed.includes(section.key);
                    return (
                      <div key={section.key} className="flex flex-col">
                        <button
                          type="button"
                          className="ph-dotted-surface sticky top-0 z-10 flex items-center gap-1.5 py-1.5 text-left"
                          onClick={() =>
                            setCollapsed((current) =>
                              current.includes(section.key)
                                ? current.filter((key) => key !== section.key)
                                : [...current, section.key],
                            )
                          }
                        >
                          {isCollapsed ? (
                            <CaretRightIcon size={10} className="text-gray-9" />
                          ) : (
                            <CaretDownIcon size={10} className="text-gray-9" />
                          )}
                          <span className="font-medium text-[12px] text-gray-9 uppercase tracking-wider">
                            {section.title}
                          </span>
                          <span className="text-[11px] text-gray-8">
                            {section.rows.length}
                          </span>
                        </button>
                        {isCollapsed ? null : (
                          <div className="flex flex-col gap-0.5 pb-2">
                            {section.rows.map((row) => (
                              <SkillCard
                                key={row.path}
                                skill={row.skill}
                                showRepoBadge={row.showRepoBadge}
                                isSelected={selectedPath === row.path}
                                onClick={() => handleSelect(row.path)}
                                scrollIntoView={scrollToPath === row.path}
                                onScrolledIntoView={handleScrolledIntoView}
                                issues={analysis[row.path]}
                              />
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>

          <ResizableSidebar
            open={!!selectedSkill}
            width={sidebarWidth}
            setWidth={setSidebarWidth}
            isResizing={isResizing}
            setIsResizing={setIsResizing}
            side="right"
          >
            {selectedSkill ? (
              <SkillDetailPanel
                key={selectedSkill.path}
                skill={selectedSkill}
                issues={analysis[selectedSkill.path] ?? []}
                canPublish={!!teamListing?.available}
                onClose={handleCloseSidebar}
              />
            ) : null}
          </ResizableSidebar>
        </div>
      )}

      <NewSkillDialog
        open={newSkillOpen}
        onOpenChange={setNewSkillOpen}
        onCreated={(path) => setSelectedPath(path)}
      />
    </div>
  );
}
