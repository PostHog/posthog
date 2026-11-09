import { useGitProviderRepositories } from "@posthog/ui/features/integrations/useGitProviderRepositories";
import { SourceControlRepositoriesList } from "./SourceControlRepositoriesList";

export function SourceControlRepositoriesSection() {
  return <SourceControlRepositoriesList {...useGitProviderRepositories()} />;
}
