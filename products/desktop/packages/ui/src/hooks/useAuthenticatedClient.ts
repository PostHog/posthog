import { useAuthenticatedClient as useClient } from "@posthog/ui/features/auth/authClient";

export function useAuthenticatedClient() {
  return useClient();
}
