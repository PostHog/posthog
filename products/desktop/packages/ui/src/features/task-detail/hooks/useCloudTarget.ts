import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSandboxCustomImages } from "../../settings/sections/environments/useSandboxCustomImages";
import { useSandboxEnvironments } from "../../settings/sections/environments/useSandboxEnvironments";
import { useSettingsStore } from "../../settings/settingsStore";
import {
  buildCloudTargetOptions,
  type CloudTarget,
  type CloudTargetOption,
  cloudTargetFromKey,
  cloudTargetKey,
  DEFAULT_CLOUD_TARGET,
  moveFavoriteFirst,
  resolveCloudTarget,
} from "../cloudTargets";

export interface UseCloudTargetOptionsResult {
  options: CloudTargetOption[];
  favoriteKey: string | null;
  toggleFavorite: (target: CloudTarget) => void;
  isLoaded: boolean;
}

export function useCloudTargetOptions(): UseCloudTargetOptionsResult {
  const { environments, isLoading: environmentsLoading } =
    useSandboxEnvironments();
  const {
    images,
    customImagesEnabled,
    isLoading: imagesLoading,
  } = useSandboxCustomImages();
  const favoriteKey = useSettingsStore((state) => state.favoriteCloudTargetKey);
  const setFavoriteKey = useSettingsStore(
    (state) => state.setFavoriteCloudTargetKey,
  );

  const options = useMemo(
    () =>
      moveFavoriteFirst(
        buildCloudTargetOptions({
          environments,
          images,
          imagesEnabled: customImagesEnabled,
        }),
        favoriteKey,
      ),
    [environments, images, customImagesEnabled, favoriteKey],
  );

  const toggleFavorite = useCallback(
    (target: CloudTarget) => {
      const key = cloudTargetKey(target);
      setFavoriteKey(favoriteKey === key ? null : key);
    },
    [favoriteKey, setFavoriteKey],
  );

  return {
    options,
    favoriteKey,
    toggleFavorite,
    isLoaded: !environmentsLoading && !imagesLoading,
  };
}

export interface UseCloudTargetSelectionResult {
  cloudTarget: CloudTarget;
  setCloudTarget: (target: CloudTarget) => void;
}

export function useCloudTargetSelection(): UseCloudTargetSelectionResult {
  const { options, favoriteKey, isLoaded } = useCloudTargetOptions();
  const settingsHydrated = useSettingsStore((state) => state._hasHydrated);
  const [cloudTarget, setCloudTargetState] =
    useState<CloudTarget>(DEFAULT_CLOUD_TARGET);
  const didResolveRef = useRef(false);

  useEffect(() => {
    if (didResolveRef.current || !settingsHydrated || !isLoaded) return;
    didResolveRef.current = true;
    setCloudTargetState(
      resolveCloudTarget(cloudTargetFromKey(favoriteKey), options),
    );
  }, [settingsHydrated, isLoaded, favoriteKey, options]);

  const setCloudTarget = useCallback((target: CloudTarget) => {
    didResolveRef.current = true;
    setCloudTargetState(target);
  }, []);

  return { cloudTarget, setCloudTarget };
}
