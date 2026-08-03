import { MagnifyingGlass, UsersThree } from "@phosphor-icons/react";
import type { TeamSkillInfo } from "@posthog/core/skills/teamSkillsService";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { Box, Flex, ScrollArea, Text, TextField } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import { useSkillsSidebarStore } from "./skillsSidebarStore";
import { TeamSkillDetailPanel } from "./TeamSkillDetailPanel";
import { TeamSkillsSection } from "./TeamSkillsSection";

interface TeamSkillsTabProps {
  /** Latest team skills, already merged with the local listing. */
  skills: TeamSkillInfo[];
}

/** Skills your team published to PostHog cloud; install to use locally. */
export function TeamSkillsTab({ skills }: TeamSkillsTabProps) {
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
    <Flex className="min-h-0 flex-1">
      <Box flexGrow="1" className="min-w-0">
        <ScrollArea type="auto" className="scroll-area-constrain-width h-full">
          <Box px="4" py="3">
            <Box pb="3">
              <TextField.Root
                size="2"
                placeholder="Search team skills..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="text-[13px]"
              >
                <TextField.Slot>
                  <MagnifyingGlass size={14} />
                </TextField.Slot>
              </TextField.Root>
            </Box>

            {filtered.length === 0 ? (
              <Flex
                align="center"
                justify="center"
                direction="column"
                gap="3"
                className="py-12"
              >
                <Box className="rounded-lg border border-gray-6 border-dashed p-4">
                  <UsersThree size={24} className="text-gray-8" />
                </Box>
                <Text className="max-w-[360px] text-center text-[13px] text-gray-10">
                  {skills.length === 0
                    ? "No team skills yet. Publish one of your skills to share it with your team."
                    : "No team skills match your search"}
                </Text>
              </Flex>
            ) : (
              <TeamSkillsSection
                skills={filtered}
                selectedName={selected?.name ?? null}
                onSelect={(skill) =>
                  setSelected((prev) => (prev?.id === skill.id ? null : skill))
                }
              />
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
          <TeamSkillDetailPanel
            key={selected.id}
            skill={selected}
            onClose={() => setSelected(null)}
          />
        )}
      </ResizableSidebar>
    </Flex>
  );
}
