import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import {
  getCapabilityLadder,
  getContextWindowOptions,
  getFastModeOptions,
  getReasoningEffortOptions,
} from "@posthog/agent/adapters/reasoning-effort";
import {
  flattenConfigValues,
  harnessForModelValue,
} from "@posthog/core/task-detail/configOptions";
import {
  applyConfigChange,
  CONTEXT_WINDOW_OPTION_CATEGORY,
  deriveInitialConfig,
  FAST_MODE_OPTION_CATEGORY,
  pickPreferredRunSelection,
} from "@posthog/core/task-detail/previewConfig";
import { useHostTRPCClient } from "@posthog/host-router/react";
import {
  type Adapter,
  adapterForModelId,
  FAST_MODE_FLAG,
  getCloudUrlFromRegion,
} from "@posthog/shared";
import { stripDisabledModelOption } from "@posthog/ui/features/sessions/modelOptionFilters";
import { useModelRolloutFlags } from "@posthog/ui/features/sessions/useModelRolloutFlags";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { logger } from "../../../shell/logger";
import { useAuthStateValue } from "../../auth/store";
import { useFeatureFlag } from "../../feature-flags/useFeatureFlag";
import { useSettingsStore } from "../../settings/settingsStore";
import { useTaskRunDefaults } from "./useTaskRunDefaults";

const log = logger.scope("preview-config");

interface PreviewConfigResult {
  configOptions: SessionConfigOption[];
  modeOption: SessionConfigOption | undefined;
  modelOption: SessionConfigOption | undefined;
  thoughtOption: SessionConfigOption | undefined;
  contextWindowOption: SessionConfigOption | undefined;
  fastModeOption: SessionConfigOption | undefined;
  isLoading: boolean;
  setConfigOption: (configId: string, value: string) => void;
}

function getOptionByCategory(
  options: SessionConfigOption[],
  category: string,
): SessionConfigOption | undefined {
  return options.find(
    (opt) => opt.category === category || opt.id === category,
  );
}

interface PreviewConfigOpts {
  /**
   * Also list the other harness's models in the model option (as a second
   * group), so the picker can switch harness from a model pick.
   */
  allHarnessModels?: boolean;
}

/**
 * Fetches config options (models, modes, effort levels) for the task input
 * page via a lightweight tRPC query. No agent session is created.
 *
 * Returns config options as local state with a setter for local updates.
 */
export function usePreviewConfig(
  adapter: Adapter,
  opts?: PreviewConfigOpts,
): PreviewConfigResult {
  const allHarnessModels = opts?.allHarnessModels ?? false;
  const hostClient = useHostTRPCClient();
  const modelFlags = useModelRolloutFlags();
  const fastModeFlagEnabled = useFeatureFlag(FAST_MODE_FLAG);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const apiHost = useMemo(
    () => (cloudRegion ? getCloudUrlFromRegion(cloudRegion) : null),
    [cloudRegion],
  );
  const [configOptions, setConfigOptions] = useState<SessionConfigOption[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const abortRef = useRef<AbortController | null>(null);
  const prevAdapterRef = useRef<Adapter | null>(null);
  const hasHydrated = useSettingsStore((state) => state._hasHydrated);
  const { defaults: runDefaults, isSettled: runDefaultsSettled } =
    useTaskRunDefaults();

  useEffect(() => {
    if (!apiHost) return;

    // Wait for the settings store to finish its async hydration before
    // resolving the model. Otherwise lastUsedModel and lastUsedAdapter read as
    // their pre-hydration defaults, the restore below is skipped, and the
    // selector silently falls back to the server default (Opus for Claude).
    // isLoading initializes to true, so the picker stays loading until hydration
    // lands and the fetch below resolves.
    if (!hasHydrated) return;

    // Same reasoning for the server-side defaults: resolving before they land
    // would seat the picker on the built-in fallback and then jump.
    if (!runDefaultsSettled) return;

    // A harness switch resets the saved selections so the new harness starts
    // on its default preset notch (and the slider face shows). A saved model
    // that already belongs to the new harness survives: that is the
    // cross-harness model pick, where the model choice drives the switch.
    if (prevAdapterRef.current !== null && prevAdapterRef.current !== adapter) {
      const { lastUsedModel } = useSettingsStore.getState();
      useSettingsStore.setState({
        lastUsedModel:
          lastUsedModel && adapterForModelId(lastUsedModel) === adapter
            ? lastUsedModel
            : null,
        lastUsedReasoningEffort: null,
        lastUsedContextWindow: null,
        lastUsedFastMode: null,
      });
    }
    prevAdapterRef.current = adapter;

    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;

    setIsLoading(true);
    // Drop the previous adapter's options so a stale model id can never be sent
    // as the current selection while the new adapter's config is loading.
    setConfigOptions([]);

    hostClient.agent.getPreviewConfigOptions
      .query(
        { apiHost, adapter, allHarnessModels: allHarnessModels || undefined },
        { signal: abort.signal },
      )
      .then((serverOptions) => {
        if (abort.signal.aborted) return;

        const options = serverOptions
          .map((option) => stripDisabledModelOption(option, modelFlags))
          .filter((option) => fastModeFlagEnabled || option.id !== "fast");

        const {
          defaultInitialTaskMode,
          lastUsedInitialTaskMode,
          defaultReasoningEffort,
          lastUsedReasoningEffort,
          lastUsedContextWindow,
          lastUsedFastMode,
          lastUsedModel,
        } = useSettingsStore.getState();

        let initial = deriveInitialConfig(
          options,
          {
            defaultInitialTaskMode,
            lastUsedInitialTaskMode,
            defaultReasoningEffort,
            lastUsedReasoningEffort,
            lastUsedContextWindow,
            lastUsedFastMode,
          },
          adapter,
        );

        // Seeding a selection is always "set the model, then carry an effort if the
        // model still offers that tier" — the restore, preference, and ladder paths
        // below differ only in where the pair comes from.
        const seedSettings = {
          defaultInitialTaskMode: "",
          lastUsedInitialTaskMode: undefined,
          defaultReasoningEffort,
          lastUsedReasoningEffort,
          lastUsedContextWindow,
          lastUsedFastMode,
        };
        const seedSelection = (
          config: SessionConfigOption[],
          model: string,
          effort?: string | null,
        ): SessionConfigOption[] => {
          const modelId = getOptionByCategory(config, "model")?.id ?? "model";
          let seeded = applyConfigChange(config, {
            adapter,
            configId: modelId,
            value: model,
            effortOptions:
              getReasoningEffortOptions(adapter, model) ?? undefined,
            contextWindowOptions:
              getContextWindowOptions(adapter, model) ?? undefined,
            fastModeOptions: fastModeFlagEnabled
              ? (getFastModeOptions(adapter, model) ?? undefined)
              : undefined,
            settings: seedSettings,
          });
          const thoughtOpt = getOptionByCategory(seeded, "thought_level");
          if (
            effort &&
            thoughtOpt &&
            flattenConfigValues(thoughtOpt).includes(effort)
          ) {
            seeded = applyConfigChange(seeded, {
              adapter,
              configId: thoughtOpt.id,
              value: effort,
              effortOptions: undefined,
              settings: seedSettings,
            });
          }
          return seeded;
        };

        // The server always returns its default model as the current value, so
        // without this the user's last (default-eligible) pick is lost on every
        // refetch/remount. Restore it through applyConfigChange so the
        // dependent effort options are recomputed for the restored model.
        const modelOpt = getOptionByCategory(initial, "model");
        // The user's explicit last pick always restores, premium families
        // included — a fresh launch must not silently downgrade the model.
        // A grouped list also holds the other harness's models, so the pick has
        // to belong to this harness or it would run on the wrong one.
        const restorableModel =
          lastUsedModel &&
          harnessForModelValue(modelOpt, lastUsedModel) === adapter
            ? lastUsedModel
            : undefined;
        if (
          restorableModel &&
          modelOpt?.type === "select" &&
          modelOpt.currentValue !== restorableModel &&
          flattenConfigValues(modelOpt).includes(restorableModel)
        ) {
          initial = seedSelection(initial, restorableModel);
        }

        // With no local pick (fresh install or a harness switch), the project or
        // user preference stored server-side decides what the composer opens on,
        // ahead of the ladder's middle notch.
        const preferred = pickPreferredRunSelection(
          runDefaults,
          adapter,
          getOptionByCategory(initial, "model"),
          lastUsedModel,
        );
        if (preferred) {
          initial = seedSelection(
            initial,
            preferred.model,
            preferred.reasoningEffort,
          );
        }

        // With no saved picks and no server-side preference, land on the ladder's
        // middle notch so the slider face is the default view.
        if (!preferred && !lastUsedModel && !lastUsedReasoningEffort) {
          const ladder = getCapabilityLadder(adapter);
          const middle = ladder[Math.floor((ladder.length - 1) / 2)];
          const midModelOpt = getOptionByCategory(initial, "model");
          if (
            middle &&
            midModelOpt?.type === "select" &&
            flattenConfigValues(midModelOpt).includes(middle.model)
          ) {
            initial = seedSelection(initial, middle.model, middle.effort);
          }
        }

        setConfigOptions(initial);
        setIsLoading(false);
      })
      .catch((error) => {
        if (abort.signal.aborted) return;
        log.error("Failed to fetch preview config options", { error });
        setIsLoading(false);
      });

    return () => {
      abort.abort();
    };
  }, [
    adapter,
    allHarnessModels,
    apiHost,
    hostClient,
    hasHydrated,
    modelFlags,
    fastModeFlagEnabled,
    runDefaults,
    runDefaultsSettled,
  ]);

  const setConfigOption = useCallback(
    (configId: string, value: string) => {
      const isModelChange = configId === "model";
      const effortOptions = isModelChange
        ? (getReasoningEffortOptions(adapter, value) ?? undefined)
        : undefined;
      const contextWindowOptions = isModelChange
        ? (getContextWindowOptions(adapter, value) ?? undefined)
        : undefined;
      const fastModeOptions =
        isModelChange && fastModeFlagEnabled
          ? (getFastModeOptions(adapter, value) ?? undefined)
          : undefined;
      const settingsStore = useSettingsStore.getState();
      if (
        configId === "context_window" &&
        (value === "200k" || value === "1m")
      ) {
        settingsStore.setLastUsedContextWindow(value);
      } else if (configId === "fast") {
        settingsStore.setLastUsedFastMode(value === "on");
      }
      setConfigOptions((prev) =>
        applyConfigChange(prev, {
          adapter,
          configId,
          value,
          effortOptions,
          contextWindowOptions,
          fastModeOptions,
          settings: {
            defaultInitialTaskMode: "",
            lastUsedInitialTaskMode: undefined,
            defaultReasoningEffort: settingsStore.defaultReasoningEffort,
            lastUsedReasoningEffort: settingsStore.lastUsedReasoningEffort,
            lastUsedContextWindow: settingsStore.lastUsedContextWindow,
            lastUsedFastMode: settingsStore.lastUsedFastMode,
          },
        }),
      );
    },
    [adapter, fastModeFlagEnabled],
  );

  const modeOption = getOptionByCategory(configOptions, "mode");
  const modelOption = getOptionByCategory(configOptions, "model");
  const thoughtOption = getOptionByCategory(configOptions, "thought_level");
  const contextWindowOption = getOptionByCategory(
    configOptions,
    CONTEXT_WINDOW_OPTION_CATEGORY,
  );
  const fastModeOption = getOptionByCategory(
    configOptions,
    FAST_MODE_OPTION_CATEGORY,
  );

  return {
    configOptions,
    modeOption,
    modelOption,
    thoughtOption,
    contextWindowOption,
    fastModeOption,
    isLoading,
    setConfigOption,
  };
}
