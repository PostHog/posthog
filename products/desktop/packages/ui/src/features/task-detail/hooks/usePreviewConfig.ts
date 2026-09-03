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

  useEffect(() => {
    if (!apiHost) return;

    // Wait for the settings store to finish its async hydration before
    // resolving the model. Otherwise lastUsedModel and lastUsedAdapter read as
    // their pre-hydration defaults, the restore below is skipped, and the
    // selector silently falls back to the server default (Opus for Claude).
    // isLoading initializes to true, so the picker stays loading until hydration
    // lands and the fetch below resolves.
    if (!hasHydrated) return;

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
          initial = applyConfigChange(initial, {
            adapter,
            configId: modelOpt.id,
            value: restorableModel,
            effortOptions:
              getReasoningEffortOptions(adapter, restorableModel) ?? undefined,
            contextWindowOptions:
              getContextWindowOptions(adapter, restorableModel) ?? undefined,
            fastModeOptions: fastModeFlagEnabled
              ? (getFastModeOptions(adapter, restorableModel) ?? undefined)
              : undefined,
            settings: {
              defaultInitialTaskMode: "",
              lastUsedInitialTaskMode: undefined,
              defaultReasoningEffort,
              lastUsedReasoningEffort,
              lastUsedContextWindow,
              lastUsedFastMode,
            },
          });
        }

        // With no saved picks (fresh install or a harness switch), land on
        // the ladder's middle notch so the slider face is the default view.
        if (!lastUsedModel && !lastUsedReasoningEffort) {
          const ladder = getCapabilityLadder(adapter);
          const middle = ladder[Math.floor((ladder.length - 1) / 2)];
          const midModelOpt = getOptionByCategory(initial, "model");
          if (
            middle &&
            midModelOpt?.type === "select" &&
            flattenConfigValues(midModelOpt).includes(middle.model)
          ) {
            const previewSettings = {
              defaultInitialTaskMode: "",
              lastUsedInitialTaskMode: undefined,
              defaultReasoningEffort,
              lastUsedReasoningEffort,
              lastUsedContextWindow,
              lastUsedFastMode,
            };
            initial = applyConfigChange(initial, {
              adapter,
              configId: midModelOpt.id,
              value: middle.model,
              effortOptions:
                getReasoningEffortOptions(adapter, middle.model) ?? undefined,
              contextWindowOptions:
                getContextWindowOptions(adapter, middle.model) ?? undefined,
              fastModeOptions: fastModeFlagEnabled
                ? (getFastModeOptions(adapter, middle.model) ?? undefined)
                : undefined,
              settings: previewSettings,
            });
            const midThoughtOpt = getOptionByCategory(initial, "thought_level");
            if (midThoughtOpt) {
              initial = applyConfigChange(initial, {
                adapter,
                configId: midThoughtOpt.id,
                value: middle.effort,
                effortOptions: undefined,
                settings: previewSettings,
              });
            }
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
