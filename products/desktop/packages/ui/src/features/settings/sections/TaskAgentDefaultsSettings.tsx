import { ArrowSquareOut } from "@phosphor-icons/react";
import type { TaskRunPreferences } from "@posthog/api-client/posthog-client";
import { buildPostHogUrl } from "@posthog/core/settings/posthogUrl";
import { Button } from "@posthog/quill";
import type { Adapter } from "@posthog/shared";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { ReasoningLevelSelector } from "@posthog/ui/features/sessions/components/ReasoningLevelSelector";
import {
  SettingsCard,
  SettingsCardRow,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { useTaskAgentDefaults } from "@posthog/ui/features/settings/hooks/useTaskAgentDefaults";
import { usePreviewConfig } from "@posthog/ui/features/task-detail/hooks/usePreviewConfig";
import { Text } from "@radix-ui/themes";
import { useCallback, useState } from "react";

/** The tasks settings page in PostHog, where the project default is set. */
const POSTHOG_SETTINGS_PATH = "/settings/environment-task-agents";

function adapterOf(preferences: TaskRunPreferences): Adapter {
  return preferences.runtime_adapter === "codex" ? "codex" : "claude";
}

/** A stored triple as prose, or a note that the level is unset. */
function describe(preferences: TaskRunPreferences, emptyLabel: string): string {
  if (!preferences.model) return emptyLabel;
  return preferences.reasoning_effort
    ? `${preferences.model} · ${preferences.reasoning_effort}`
    : preferences.model;
}

/** Picker for this user's own default, persisted to PostHog rather than to the device. */
function MyDefaultPicker({
  preferences,
  disabled,
  onSave,
}: {
  preferences: TaskRunPreferences;
  disabled: boolean;
  onSave: (next: TaskRunPreferences) => void;
}) {
  const [adapter, setAdapter] = useState<Adapter>(adapterOf(preferences));
  const { modelOption, thoughtOption, isLoading, setConfigOption } =
    usePreviewConfig(adapter);

  const handleModelChange = useCallback(
    (model: string) => {
      if (modelOption) setConfigOption(modelOption.id, model);
      // The effort belongs to the model it was chosen against, so a model switch drops
      // it rather than carrying an effort the new model may not support.
      onSave({ runtime_adapter: adapter, model, reasoning_effort: null });
    },
    [modelOption, setConfigOption, adapter, onSave],
  );

  const handleEffortChange = useCallback(
    (effort: string) => {
      if (thoughtOption) setConfigOption(thoughtOption.id, effort);
      if (!preferences.model) return;
      onSave({
        runtime_adapter: adapter,
        model: preferences.model,
        reasoning_effort: effort || null,
      });
    },
    [thoughtOption, setConfigOption, adapter, preferences.model, onSave],
  );

  return (
    <ReasoningLevelSelector
      modelOption={modelOption}
      thoughtOption={thoughtOption}
      adapter={adapter}
      onModelChange={handleModelChange}
      onChange={handleEffortChange}
      onAdapterChange={setAdapter}
      onConfigOptionChange={(configId, value) => {
        if (modelOption && configId === modelOption.id) {
          handleModelChange(value);
        } else if (thoughtOption && configId === thoughtOption.id) {
          handleEffortChange(value);
        }
      }}
      disabled={disabled}
      isLoading={isLoading}
    />
  );
}

/**
 * What agent runs in this project launch with when nobody picks a model.
 *
 * Both levels are shown because only seeing the resolved answer leaves "why this
 * model" unanswerable. The project default is read-only here: it is admin-gated in
 * PostHog, so this links out rather than offering a control that would be refused.
 */
export function TaskAgentDefaultsSettings() {
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const isAuthenticated = useAuthStateValue(
    (state) => state.status === "authenticated",
  );
  const {
    teamPreferences,
    myPreferences,
    resolved,
    isLoading,
    isSaving,
    save,
    reset,
  } = useTaskAgentDefaults();

  const settingsUrl = buildPostHogUrl(POSTHOG_SETTINGS_PATH, cloudRegion);

  if (!isAuthenticated) {
    return (
      <Text className="text-(--gray-11) text-sm">
        Sign in to PostHog to see the defaults this project runs with.
      </Text>
    );
  }

  return (
    <div className="flex flex-col gap-7">
      <SettingsCard>
        <SettingsCardRow
          label="Project default"
          description="What everyone on this project inherits. Only project admins can change it."
        >
          <div className="flex items-center gap-2">
            <Text className="text-(--gray-11) text-sm">
              {isLoading
                ? "Loading…"
                : describe(teamPreferences, "No project default")}
            </Text>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!settingsUrl}
              onClick={() => {
                if (settingsUrl) window.open(settingsUrl, "_blank");
              }}
            >
              Manage
              <ArrowSquareOut size={12} />
            </Button>
          </div>
        </SettingsCardRow>

        <SettingsCardRow
          label="My default"
          description="Overrides the project default for your own runs, everywhere in PostHog — not just this app."
        >
          <MyDefaultPicker
            preferences={myPreferences}
            disabled={isLoading || isSaving}
            onSave={(next) => void save(next)}
          />
        </SettingsCardRow>

        <SettingsCardRow
          label="Reset my default"
          description={
            myPreferences.model
              ? "Go back to inheriting the project default."
              : "You're already inheriting the project default."
          }
        >
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!myPreferences.model || isSaving}
            onClick={() => void reset()}
          >
            Use project default
          </Button>
        </SettingsCardRow>
      </SettingsCard>

      <Text className="text-(--gray-11) text-sm">
        {resolved.model
          ? `Runs you start without picking a model use ${resolved.model}${
              resolved.reasoning_effort ? ` · ${resolved.reasoning_effort}` : ""
            }, from ${resolved.source === "user" ? "your default" : "the project default"}.`
          : "No default is set — runs use each surface's built-in model."}
      </Text>
    </div>
  );
}
