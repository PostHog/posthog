import type { TicketView } from "@posthog/api-client/posthog-client";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { SUPPORT_TICKET_VIEWS_QUERY_KEY } from "@posthog/ui/features/support/hooks/useSupportTicketViews";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";

export interface SetTicketViewFavoritedInput {
  shortId: string;
  favorited: boolean;
}

/**
 * Favorite or unfavorite a saved view. The only write the Support surface
 * makes against views — a single-field PATCH, so it needs no understanding of
 * the filters blob that create and rename would.
 *
 * Optimistic, because the star also re-sorts the rail: waiting on the round
 * trip would make the row jump a beat after the click. Written in `onMutate`
 * so the last *click* wins rather than the last response to land.
 */
export function useSetTicketViewFavorited() {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ shortId, favorited }: SetTicketViewFavoritedInput) => {
      if (!client) throw new Error("Not authenticated");
      return await client.setTicketViewFavorited(shortId, favorited);
    },
    onMutate: async ({ shortId, favorited }) => {
      await queryClient.cancelQueries({
        queryKey: SUPPORT_TICKET_VIEWS_QUERY_KEY,
      });
      const previous = queryClient.getQueryData<TicketView[]>(
        SUPPORT_TICKET_VIEWS_QUERY_KEY,
      );
      queryClient.setQueryData<TicketView[]>(
        SUPPORT_TICKET_VIEWS_QUERY_KEY,
        (views) =>
          views?.map((view) =>
            view.short_id === shortId
              ? { ...view, is_favorited: favorited }
              : view,
          ),
      );
      return { previous };
    },
    onError: (_error, _input, context) => {
      queryClient.setQueryData(
        SUPPORT_TICKET_VIEWS_QUERY_KEY,
        context?.previous,
      );
      toast.error("Couldn't update this view");
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: SUPPORT_TICKET_VIEWS_QUERY_KEY,
      });
    },
  });
}
