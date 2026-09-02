import { TEAM_SKILLS_SERVICE } from "@posthog/core/skills/identifiers";
import {
  markInstalledTeamSkills,
  type TeamSkillsService,
} from "@posthog/core/skills/teamSkillsService";
import { useService } from "@posthog/di/react";
import type { SkillInfo } from "@posthog/shared";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMemo } from "react";

export const teamSkillsKeys = {
  all: ["team-skills"] as const,
  list: () => [...teamSkillsKeys.all, "list"] as const,
  detail: (name: string) => [...teamSkillsKeys.all, "detail", name] as const,
  file: (name: string, path: string) =>
    [...teamSkillsKeys.all, "file", name, path] as const,
};

export function useTeamSkills(localSkills: SkillInfo[]) {
  const service = useService<TeamSkillsService>(TEAM_SKILLS_SERVICE);
  const query = useAuthenticatedQuery(
    teamSkillsKeys.list(),
    (client) => service.listTeamSkills(client),
    { staleTime: 60_000, retry: false },
  );

  // Marking is pure and local-only, so local skill changes never refetch
  // the team listing.
  const localNames = useMemo(
    () => [...new Set(localSkills.map((s) => s.name))],
    [localSkills],
  );
  const data = useMemo(
    () =>
      query.data ? markInstalledTeamSkills(query.data, localNames) : undefined,
    [query.data, localNames],
  );

  return { ...query, data };
}

export function useTeamSkillDetail(name: string | null) {
  return useAuthenticatedQuery(
    teamSkillsKeys.detail(name ?? ""),
    (client) => client.getLlmSkillByName(name ?? ""),
    { enabled: name !== null, staleTime: 60_000, retry: false },
  );
}

export function useTeamSkillFile(name: string, filePath: string | null) {
  return useAuthenticatedQuery(
    teamSkillsKeys.file(name, filePath ?? ""),
    (client) => client.getLlmSkillFile(name, filePath ?? ""),
    { enabled: filePath !== null, staleTime: 60_000, retry: false },
  );
}
