import {
  CaretLeft,
  CaretRight,
  Lightning,
  MagnifyingGlass,
} from "@phosphor-icons/react";
import type { DiscoveredTask } from "@posthog/core/setup/types";
import { Flex, Text } from "@radix-ui/themes";
import { AnimatePresence, motion } from "framer-motion";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useActiveRepoStore } from "../../../shell/activeRepoStore";
import { DiscoveredTaskDetailDialog } from "../../setup/DiscoveredTaskDetailDialog";
import { SetupScanFeed } from "../../setup/SetupScanFeed";
import {
  isTaskForRepo,
  selectRepoDiscovery,
  selectRepoEnricher,
  useSetupStore,
} from "../../setup/setupStore";
import { SuggestedTaskCard } from "./SuggestedTaskCard";

const VISIBLE_LIMIT = 3;
const DEFAULT_LOG_LINES = 4;

const TOP_MARGIN = 12;
const HEADER_HEIGHT = 24;
const GAP = 8;
const SCAN_PILL_HEIGHT = 52;
const CARD_HEIGHT = 56;
const BOTTOM_PADDING = 56;
const LOG_LINE_HEIGHT = 24;
const LOG_FEED_PADDING = 16;

const fadeMotion = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.15 },
};

const pagerButtonClass =
  "flex h-5 w-5 cursor-pointer items-center justify-center rounded text-(--gray-11) hover:bg-(--gray-3) hover:text-(--gray-12) disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-(--gray-11)";

export function SuggestedTasksPanel({ leading }: { leading?: ReactNode }) {
  const selectedDirectory = useActiveRepoStore((s) => s.path);
  const discoveredTasks = useSetupStore((s) =>
    s.discoveredTasks.filter((task) =>
      isTaskForRepo(task, selectedDirectory || null),
    ),
  );
  const discoveryStatus = useSetupStore(
    (s) => selectRepoDiscovery(s, selectedDirectory).status,
  );
  const enricherStatus = useSetupStore(
    (s) => selectRepoEnricher(s, selectedDirectory).status,
  );
  const discoveryFeed = useSetupStore(
    (s) => selectRepoDiscovery(s, selectedDirectory).feed,
  );
  const removeDiscoveredTask = useSetupStore((s) => s.removeDiscoveredTask);

  const [detailTask, setDetailTask] = useState<DiscoveredTask | null>(null);
  const [pageStart, setPageStart] = useState(0);
  const [pageDirection, setPageDirection] = useState<1 | -1>(1);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset pagination on repo change
  useEffect(() => {
    setPageStart(0);
    setPageDirection(1);
    setDetailTask(null);
  }, [selectedDirectory]);

  const containerRef = useRef<HTMLDivElement>(null);
  const [availableHeight, setAvailableHeight] = useState<number>(() =>
    typeof window === "undefined"
      ? Number.POSITIVE_INFINITY
      : window.innerHeight,
  );

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const measure = () => {
      const rect = el.getBoundingClientRect();
      setAvailableHeight(window.innerHeight - rect.top);
    };

    measure();
    const observer = new ResizeObserver(measure);
    const parent = el.parentElement;
    if (parent) observer.observe(parent);
    observer.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  const handleDismiss = useCallback(
    (task: DiscoveredTask) => {
      removeDiscoveredTask(task.id, task.repoPath ?? null);
    },
    [removeDiscoveredTask],
  );

  const handleSelectTask = useCallback((task: DiscoveredTask) => {
    setDetailTask(task);
  }, []);

  const handleCloseDetail = useCallback(() => {
    setDetailTask(null);
  }, []);

  const hasTasks = discoveredTasks.length > 0;
  const showEnricherFeed = !hasTasks && enricherStatus === "running";
  const showDiscoveryFeed = discoveryStatus === "running";

  if (!hasTasks && !showEnricherFeed && !showDiscoveryFeed && !leading)
    return null;

  const totalTasks = discoveredTasks.length;
  const desiredVisible = Math.min(totalTasks, VISIBLE_LIMIT);
  const discoveryFeedHasEntries = discoveryFeed.recentEntries.length > 0;

  const measureTotalHeight = (cardCount: number, logLines: number): number => {
    const sections: number[] = [];
    if (hasTasks) sections.push(HEADER_HEIGHT);
    if (cardCount > 0) {
      sections.push(cardCount * CARD_HEIGHT + Math.max(0, cardCount - 1) * GAP);
    }
    if (showEnricherFeed) sections.push(SCAN_PILL_HEIGHT);
    if (showDiscoveryFeed) {
      let h = SCAN_PILL_HEIGHT;
      if (logLines > 0 && discoveryFeedHasEntries) {
        h += LOG_FEED_PADDING + logLines * LOG_LINE_HEIGHT;
      }
      sections.push(h);
    }
    const sectionsTotal = sections.reduce((a, b) => a + b, 0);
    const gapsTotal = Math.max(0, sections.length - 1) * GAP;
    return TOP_MARGIN + sectionsTotal + gapsTotal + BOTTOM_PADDING;
  };

  let visibleCount = desiredVisible;
  let logLines = showDiscoveryFeed ? DEFAULT_LOG_LINES : 0;
  if (Number.isFinite(availableHeight)) {
    while (measureTotalHeight(visibleCount, logLines) > availableHeight) {
      if (logLines > 0) logLines -= 1;
      else if (visibleCount > 0) visibleCount -= 1;
      else break;
    }
  }

  const effectivePageStart =
    visibleCount > 0 && pageStart < totalTasks ? pageStart : 0;

  const visibleTasks = discoveredTasks.slice(
    effectivePageStart,
    effectivePageStart + visibleCount,
  );

  const canGoPrev = effectivePageStart > 0;
  const canGoNext = effectivePageStart + visibleTasks.length < totalTasks;
  const showPager = visibleCount > 0 && totalTasks > visibleCount;
  const currentPage =
    visibleCount > 0 ? Math.floor(effectivePageStart / visibleCount) + 1 : 1;
  const totalPages =
    visibleCount > 0 ? Math.max(1, Math.ceil(totalTasks / visibleCount)) : 1;

  const handleNext = () => {
    setPageDirection(1);
    setPageStart(effectivePageStart + visibleCount);
  };

  const handlePrev = () => {
    setPageDirection(-1);
    setPageStart(Math.max(0, effectivePageStart - visibleCount));
  };

  return (
    <div ref={containerRef} className="mt-3 flex flex-col gap-2">
      {(hasTasks || leading) && (
        <Flex align="center" justify="between" className="px-2.5">
          <Text size="1" weight="medium" className="text-(--gray-11)">
            Suggestions
          </Text>
          {showPager && (
            <Flex align="center" gap="2">
              <Text size="1" className="text-(--gray-10) tabular-nums">
                {currentPage} / {totalPages}
              </Text>
              <Flex align="center" gap="0.5">
                <button
                  type="button"
                  disabled={!canGoPrev}
                  onClick={handlePrev}
                  aria-label="Previous suggestions"
                  className={pagerButtonClass}
                >
                  <CaretLeft size={12} weight="bold" />
                </button>
                <button
                  type="button"
                  disabled={!canGoNext}
                  onClick={handleNext}
                  aria-label="More suggestions"
                  className={pagerButtonClass}
                >
                  <CaretRight size={12} weight="bold" />
                </button>
              </Flex>
            </Flex>
          )}
        </Flex>
      )}
      {leading}
      {hasTasks && (
        <div className="relative">
          <AnimatePresence mode="wait" initial={false} custom={pageDirection}>
            <motion.div
              key={effectivePageStart}
              custom={pageDirection}
              initial="enter"
              animate="center"
              exit="exit"
              variants={{
                enter: (dir: number) => ({ x: dir * 32, opacity: 0 }),
                center: {
                  x: 0,
                  opacity: 1,
                  transition: {
                    x: { duration: 0.22, ease: [0.22, 1, 0.36, 1] },
                    opacity: { duration: 0.18, ease: "easeOut" },
                  },
                },
                exit: (dir: number) => ({
                  x: -dir * 32,
                  opacity: 0,
                  transition: { duration: 0.13, ease: "easeIn" },
                }),
              }}
              className="flex flex-col gap-2"
            >
              <AnimatePresence mode="sync" initial={false}>
                {visibleTasks.map((task) => (
                  <SuggestedTaskCard
                    key={task.id}
                    task={task}
                    onSelect={handleSelectTask}
                    onDismiss={handleDismiss}
                  />
                ))}
              </AnimatePresence>
            </motion.div>
          </AnimatePresence>
        </div>
      )}
      <AnimatePresence initial={false}>
        {showEnricherFeed && (
          <motion.div key="enricher" layout {...fadeMotion}>
            <SetupScanFeed
              label="Quick wins"
              icon={Lightning}
              color="amber"
              currentTool={null}
              activeLabelOverride="Checking your PostHog setup…"
              recentEntries={[]}
              isDone={false}
            />
          </motion.div>
        )}
        {showDiscoveryFeed && (
          <motion.div key="discovery" layout {...fadeMotion}>
            <SetupScanFeed
              label="Analyzing your codebase"
              description="Looking for bugs, dead code, and improvements"
              icon={MagnifyingGlass}
              color="orange"
              currentTool={discoveryFeed.currentTool}
              recentEntries={discoveryFeed.recentEntries}
              isDone={false}
              maxLogLines={logLines}
            />
          </motion.div>
        )}
      </AnimatePresence>
      <DiscoveredTaskDetailDialog
        task={detailTask}
        onClose={handleCloseDetail}
      />
    </div>
  );
}
