import { ChannelDocumentConflictError } from "@posthog/api-client/posthog-client";
import type { CaptureSource } from "@posthog/core/channel-documents/markdown";
import {
  formatPlanCapture,
  formatTodoCapture,
  toggleTaskCheckbox,
} from "@posthog/core/channel-documents/markdown";
import type {
  ChannelDocument,
  ChannelDocumentKind,
} from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

export const CHANNEL_DOCUMENTS_QUERY_KEY = (channelId: string) =>
  ["channel-documents", channelId] as const;

// Teammates' captures and checkbox toggles arrive on the next poll; the panel
// is only mounted while open, so the interval costs nothing otherwise.
const DOCUMENTS_POLL_INTERVAL_MS = 15_000;

export const DEFAULT_DOC_NAMES: Record<ChannelDocumentKind, string> = {
  todo: "Todos",
  plan: "Plan",
};

export function useChannelDocuments(
  channelId: string | null | undefined,
  options?: { enabled?: boolean },
) {
  return useAuthenticatedQuery<ChannelDocument[]>(
    channelId
      ? CHANNEL_DOCUMENTS_QUERY_KEY(channelId)
      : (["channel-documents", "none"] as const),
    async (client) => (channelId ? client.getChannelDocuments(channelId) : []),
    {
      enabled: Boolean(channelId) && (options?.enabled ?? true),
      staleTime: 0,
      refetchOnMount: "always",
      refetchInterval: DOCUMENTS_POLL_INTERVAL_MS,
    },
  );
}

function useUpsertDocument() {
  const queryClient = useQueryClient();
  return useCallback(
    (channelId: string, document: ChannelDocument) => {
      queryClient.setQueryData<ChannelDocument[]>(
        CHANNEL_DOCUMENTS_QUERY_KEY(channelId),
        (prev) => {
          if (!prev) return [document];
          const exists = prev.some((d) => d.id === document.id);
          return exists
            ? prev.map((d) => (d.id === document.id ? document : d))
            : [document, ...prev];
        },
      );
    },
    [queryClient],
  );
}

export interface CaptureInput {
  /** Backend task-channel id; when absent the capture lands in #me. */
  channelId?: string | null;
  docKind: ChannelDocumentKind;
  text: string;
  source?: CaptureSource;
}

/**
 * The selection-capture write path: resolve the target channel (falling back
 * to the personal #me channel), resolve-or-create the default doc for the
 * kind, then append the formatted block. Appends serialize server-side, so
 * this never conflicts — two people capturing at once both land.
 */
export function useCaptureToChannelDocument() {
  const client = useOptionalAuthenticatedClient();
  const upsert = useUpsertDocument();

  return useMutation({
    mutationFn: async (input: CaptureInput) => {
      if (!client) throw new Error("Not authenticated");
      let channelId = input.channelId ?? null;
      if (!channelId) {
        const channels = await client.getTaskChannels();
        channelId =
          channels.find((c) => c.channel_type === "personal")?.id ?? null;
        if (!channelId) throw new Error("No personal channel");
      }
      const doc = await client.createChannelDocument(channelId, {
        name: DEFAULT_DOC_NAMES[input.docKind],
        docKind: input.docKind,
      });
      const block =
        input.docKind === "todo"
          ? formatTodoCapture(input.text, input.source)
          : formatPlanCapture(input.text, input.source);
      const document = await client.appendChannelDocument(
        channelId,
        doc.id,
        block,
      );
      return { document, channelId };
    },
    onSuccess: ({ document, channelId }) => upsert(channelId, document),
  });
}

/** Result of a checkbox toggle: `conflict` means the doc moved underneath us twice. */
export type ToggleCheckboxResult = "toggled" | "stale" | "conflict";

export function useChannelDocumentMutations(channelId: string | null) {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const upsert = useUpsertDocument();

  const invalidate = useCallback(() => {
    if (!channelId) return;
    void queryClient.invalidateQueries({
      queryKey: CHANNEL_DOCUMENTS_QUERY_KEY(channelId),
    });
  }, [channelId, queryClient]);

  const toggleMutation = useMutation({
    mutationFn: async (input: {
      document: ChannelDocument;
      checkboxIndex: number;
    }): Promise<ToggleCheckboxResult> => {
      if (!client) throw new Error("Not authenticated");
      if (!channelId) throw new Error("No channel");
      const attempt = async (
        doc: ChannelDocument,
      ): Promise<ChannelDocument | null> => {
        const next = toggleTaskCheckbox(doc.content, input.checkboxIndex);
        if (next === null) return null;
        return client.updateChannelDocument(channelId, doc.id, {
          content: next,
          expectedVersion: doc.current_version,
        });
      };
      try {
        const updated = await attempt(input.document);
        if (!updated) return "stale";
        upsert(channelId, updated);
        return "toggled";
      } catch (error) {
        if (!(error instanceof ChannelDocumentConflictError)) throw error;
        // Someone else wrote since our snapshot: retry once against the fresh
        // content so a lost race doesn't cost the user their click.
        const fresh = (await client.getChannelDocuments(channelId)).find(
          (d) => d.id === input.document.id,
        );
        if (!fresh) return "stale";
        try {
          const retried = await attempt(fresh);
          if (!retried) return "stale";
          upsert(channelId, retried);
          return "toggled";
        } catch (retryError) {
          if (retryError instanceof ChannelDocumentConflictError)
            return "conflict";
          throw retryError;
        }
      }
    },
    onSettled: invalidate,
  });

  const saveMutation = useMutation({
    mutationFn: async (input: {
      documentId: string;
      content: string;
      expectedVersion: number;
    }) => {
      if (!client) throw new Error("Not authenticated");
      if (!channelId) throw new Error("No channel");
      return client.updateChannelDocument(channelId, input.documentId, {
        content: input.content,
        expectedVersion: input.expectedVersion,
      });
    },
    onSuccess: (document) => channelId && upsert(channelId, document),
  });

  const createMutation = useMutation({
    mutationFn: async (docKind: ChannelDocumentKind) => {
      if (!client) throw new Error("Not authenticated");
      if (!channelId) throw new Error("No channel");
      return client.createChannelDocument(channelId, {
        name: DEFAULT_DOC_NAMES[docKind],
        docKind,
      });
    },
    onSuccess: (document) => channelId && upsert(channelId, document),
  });

  const deleteMutation = useMutation({
    mutationFn: async (documentId: string) => {
      if (!client) throw new Error("Not authenticated");
      if (!channelId) throw new Error("No channel");
      await client.deleteChannelDocument(channelId, documentId);
      return documentId;
    },
    onSuccess: (documentId) => {
      if (!channelId) return;
      queryClient.setQueryData<ChannelDocument[]>(
        CHANNEL_DOCUMENTS_QUERY_KEY(channelId),
        (prev) => prev?.filter((d) => d.id !== documentId),
      );
    },
  });

  return {
    toggleCheckbox: toggleMutation.mutateAsync,
    isToggling: toggleMutation.isPending,
    save: saveMutation.mutateAsync,
    isSaving: saveMutation.isPending,
    saveError: saveMutation.error,
    create: createMutation.mutateAsync,
    isCreating: createMutation.isPending,
    remove: deleteMutation.mutateAsync,
    isRemoving: deleteMutation.isPending,
  };
}
