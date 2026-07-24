import { ArrowsClockwise, Gift, Spinner, X } from "@phosphor-icons/react";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useUpdateBannerStore } from "@posthog/ui/features/updates/updateBannerStore";
import { useUpdateModalStore } from "@posthog/ui/features/updates/updateModalStore";
import {
  useInstallUpdate,
  useUpdateView,
} from "@posthog/ui/features/updates/updateStore";
import { Box } from "@radix-ui/themes";
import { AnimatePresence, motion } from "framer-motion";

interface UpdateBannerProps {
  variant?: "sidebar" | "compact";
}

export function UpdateBanner({ variant = "sidebar" }: UpdateBannerProps) {
  const { status, version, availableVersion, downloadPercent, isEnabled } =
    useUpdateView();
  const installUpdate = useInstallUpdate();
  const openModal = useUpdateModalStore((state) => state.open);
  const canDismiss = useSettingsStore(
    (state) => state.dismissibleUpdateBanners,
  );
  const dismissedVersion = useUpdateBannerStore(
    (state) => state.dismissedVersion,
  );
  const dismissBanner = useUpdateBannerStore((state) => state.dismiss);

  const dismissKey = version ?? availableVersion ?? "unknown";
  const isDismissed = canDismiss && dismissedVersion === dismissKey;

  const isVisible =
    isEnabled &&
    !isDismissed &&
    (status === "available" ||
      status === "downloading" ||
      status === "ready" ||
      status === "installing");

  const percent = Math.round(downloadPercent ?? 0);

  if (variant === "compact") {
    return (
      <AnimatePresence>
        {isVisible && (
          <motion.div
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -8 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
          >
            {status === "available" && (
              <div className="group flex items-center gap-1">
                <button
                  type="button"
                  className="flex items-center gap-1.5 rounded-2 border border-(--green-a5) bg-(--green-a3) px-2.5 py-1 font-medium text-(--green-11) text-[13px] transition-colors hover:bg-(--green-a4)"
                  onClick={openModal}
                >
                  <Gift size={14} weight="duotone" />
                  <span>Update available</span>
                </button>
                {canDismiss && (
                  <DismissButton onClick={() => dismissBanner(dismissKey)} />
                )}
              </div>
            )}

            {status === "downloading" && (
              <button
                type="button"
                className="flex items-center gap-1.5 text-(--green-11) text-[13px] opacity-70"
                onClick={openModal}
              >
                <Spinner size={14} className="animate-spin" />
                <span>Downloading update... {percent}%</span>
              </button>
            )}

            {status === "ready" && (
              <div className="group flex items-center gap-1">
                <button
                  type="button"
                  className="flex items-center gap-1.5 rounded-2 border border-(--green-a5) bg-(--green-a3) px-2.5 py-1 font-medium text-(--green-11) text-[13px] transition-colors hover:bg-(--green-a4)"
                  onClick={() => void installUpdate()}
                >
                  <Gift size={14} weight="duotone" />
                  <span>
                    {version ? `${version} ready` : "Update ready"} — Restart
                  </span>
                </button>
                {canDismiss && (
                  <DismissButton onClick={() => dismissBanner(dismissKey)} />
                )}
              </div>
            )}

            {status === "installing" && (
              <div className="flex items-center gap-1.5 text-(--green-11) text-[13px] opacity-70">
                <ArrowsClockwise size={14} className="animate-spin" />
                <span>Restarting...</span>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    );
  }

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          className="shrink-0 overflow-hidden"
        >
          <AnimatePresence mode="wait">
            {status === "available" && (
              <BannerCard key="available">
                <div className="group relative flex w-full items-center gap-3 rounded-md border border-[var(--green-a5)] bg-[var(--green-a3)] px-3 py-2.5 text-[13px] text-[var(--green-11)]">
                  <Gift size={20} weight="duotone" className="shrink-0" />
                  <button
                    type="button"
                    onClick={openModal}
                    className="flex min-w-0 flex-1 flex-col gap-0.5 text-left"
                  >
                    <span className="truncate font-medium">
                      Update available
                    </span>
                    <span className="truncate text-[11px] text-[var(--green-a11)]">
                      {availableVersion
                        ? `Version ${availableVersion}`
                        : "View details"}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={openModal}
                    className="shrink-0 rounded-2 bg-[var(--green-a4)] px-2.5 py-1 font-medium text-[12px] text-[var(--green-11)] transition-colors hover:bg-[var(--green-a5)]"
                  >
                    View
                  </button>
                  {canDismiss && (
                    <DismissButton
                      variant="overlay"
                      onClick={() => dismissBanner(dismissKey)}
                    />
                  )}
                </div>
              </BannerCard>
            )}

            {status === "downloading" && (
              <BannerCard key="downloading">
                <button
                  type="button"
                  onClick={openModal}
                  className="flex w-full flex-col gap-1.5 rounded-md border border-[var(--green-a5)] bg-[var(--green-a3)] px-3 py-2.5 text-[13px] text-[var(--green-11)]"
                >
                  <div className="flex w-full items-center justify-between">
                    <span className="font-medium">Downloading update...</span>
                    <span className="text-[11px] text-[var(--green-a11)]">
                      {percent}%
                    </span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--green-a4)]">
                    <div
                      className="h-full rounded-full bg-[var(--green-9)] transition-all"
                      style={{ width: `${percent}%` }}
                    />
                  </div>
                </button>
              </BannerCard>
            )}

            {status === "ready" && (
              <BannerCard key="ready">
                <div className="group relative flex w-full items-center gap-3 rounded-md border border-[var(--green-a5)] bg-[var(--green-a3)] px-3 py-2.5 text-[13px] text-[var(--green-11)]">
                  <motion.div
                    className="shrink-0"
                    animate={{ rotate: [0, -12, 12, -8, 8, -4, 0] }}
                    transition={{
                      duration: 0.6,
                      repeat: Infinity,
                      repeatDelay: 4,
                      ease: "easeInOut",
                    }}
                  >
                    <Gift size={20} weight="duotone" />
                  </motion.div>
                  <button
                    type="button"
                    onClick={openModal}
                    className="flex min-w-0 flex-1 flex-col gap-0.5 text-left"
                  >
                    <span className="font-medium">
                      {version ? `${version} ready` : "Update ready"}
                    </span>
                    <span className="text-[11px] text-[var(--green-a11)]">
                      Restart to apply
                    </span>
                  </button>
                  <button
                    type="button"
                    className="shrink-0 rounded-2 bg-[var(--green-a4)] px-2 py-1 font-medium text-[12px] text-[var(--green-11)] transition-colors hover:bg-[var(--green-a5)]"
                    onClick={() => void installUpdate()}
                  >
                    Restart
                  </button>
                  {canDismiss && (
                    <DismissButton
                      variant="overlay"
                      onClick={() => dismissBanner(dismissKey)}
                    />
                  )}
                </div>
              </BannerCard>
            )}

            {status === "installing" && (
              <BannerCard key="installing">
                <div className="flex w-full items-center gap-2 rounded-md border border-[var(--green-a5)] bg-[var(--green-a3)] px-3 py-2.5 text-[13px] text-[var(--green-11)]">
                  <ArrowsClockwise
                    size={16}
                    className="shrink-0 animate-spin"
                  />
                  <span className="font-medium">Restarting...</span>
                </div>
              </BannerCard>
            )}
          </AnimatePresence>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function DismissButton({
  onClick,
  variant = "inline",
}: {
  onClick: () => void;
  variant?: "inline" | "overlay";
}) {
  const className =
    variant === "overlay"
      ? "absolute -top-1.5 -right-1.5 rounded-full border border-(--green-a5) bg-(--gray-2) p-1 text-(--green-11) opacity-0 transition-all focus-visible:opacity-100 group-hover:opacity-100 hover:bg-(--green-a4)"
      : "shrink-0 rounded-2 p-1 text-(--green-a11) opacity-0 transition-all focus-visible:opacity-100 group-hover:opacity-100 hover:bg-(--green-a4) hover:text-(--green-11)";

  return (
    <button
      type="button"
      aria-label="Dismiss update banner"
      title="Dismiss"
      className={className}
      onClick={onClick}
    >
      <X size={variant === "overlay" ? 10 : 12} weight="bold" />
    </button>
  );
}

function BannerCard({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
    >
      <Box className="p-2">{children}</Box>
    </motion.div>
  );
}
