import { UsersThreeIcon } from "@phosphor-icons/react";
import type { TeamSkillInfo } from "@posthog/core/skills/teamSkillsService";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { useMemo, useState } from "react";
import { SkillListSkeleton } from "./SkillSkeletons";
import { SkillsToolbar } from "./SkillsToolbar";
import { useSkillsSidebarStore } from "./skillsSidebarStore";
import { TeamSkillDetailPanel } from "./TeamSkillDetailPanel";
import { TeamSkillsSection } from "./TeamSkillsSection";

interface TeamSkillsTabProps {
  /** Latest team skills, already merged with the local listing. */
  skills: TeamSkillInfo[];
  loading?: boolean;
}

/** Skills your team published to PostHog cloud; install to use locally. */
export function TeamSkillsTab({ skills, loading }: TeamSkillsTabProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selected, setSelected] = useState<TeamSkillInfo | null>(null);

  const {
    width: sidebarWidth,
    setWidth: setSidebarWidth,
    isResizing,
    setIsResizing,
  } = useSkillsSidebarStore();

  const filtered = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return skills;
    return skills.filter(
      (skill) =>
        skill.name.toLowerCase().includes(query) ||
        skill.description.toLowerCase().includes(query),
    );
  }, [skills, searchQuery]);

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <SkillsToolbar
          placeholder="Search team skills"
          value={searchQuery}
          onChange={setSearchQuery}
        />

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-5xl px-4 py-3">
            {loading && skills.length === 0 ? (
              <SkillListSkeleton rows={5} />
            ) : filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-3 py-12">
                <div className="rounded-lg border border-gray-6 border-dashed p-4">
                  <UsersThreeIcon size={24} className="text-gray-8" />
                </div>
                <p className="max-w-[360px] text-center text-[13px] text-gray-10">
                  {skills.length === 0
                    ? "No team skills yet. Publish one of your skills to share it with your team."
                    : "No team skills match your search"}
                </p>
              </div>
            ) : (
              <TeamSkillsSection
                skills={filtered}
                selectedName={selected?.name ?? null}
                onSelect={(skill) =>
                  setSelected((prev) => (prev?.id === skill.id ? null : skill))
                }
              />
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
          <TeamSkillDetailPanel
            key={selected.id}
            skill={selected}
            onClose={() => setSelected(null)}
          />
        )}
      </ResizableSidebar>
    </div>
  );
}
