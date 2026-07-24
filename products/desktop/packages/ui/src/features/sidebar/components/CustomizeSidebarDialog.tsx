import { type DragDropEvents, DragDropProvider } from "@dnd-kit/react";
import { useSortable } from "@dnd-kit/react/sortable";
import {
  Bell,
  DotsSixVertical,
  EnvelopeSimple,
  HashIcon,
  Lightning,
  RepeatIcon,
  SlidersHorizontal,
} from "@phosphor-icons/react";
import { LOOPS_FLAG, PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import {
  CUSTOMIZABLE_NAV_ITEMS,
  type CustomizableNavItem,
  type CustomizableNavItemId,
  isNavItemVisible,
  moveNavItem,
  orderedNavItems,
} from "@posthog/ui/features/sidebar/constants";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { track } from "@posthog/ui/shell/analytics";
import { Button, Checkbox, Flex, Text } from "@radix-ui/themes";
import { type RefCallback, useRef, useState } from "react";

const ITEM_ICONS: Record<
  CustomizableNavItemId,
  React.ComponentType<{ size?: number | string }>
> = {
  inbox: EnvelopeSimple,
  "command-center": Lightning,
  contexts: HashIcon,
  activity: Bell,
  configure: SlidersHorizontal,
  loops: RepeatIcon,
};

function sameOrder(
  a: readonly CustomizableNavItemId[],
  b: readonly CustomizableNavItemId[],
): boolean {
  return a.length === b.length && a.every((id, i) => id === b[i]);
}

export function CustomizeSidebarSettings() {
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG, import.meta.env.DEV);
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const channelsEnabled = useSidebarStore((s) => s.channelsEnabled);
  const navItemOverrides = useSidebarStore((s) => s.navItemOverrides);
  const navItemOrder = useSidebarStore((s) => s.navItemOrder);
  const setNavItemVisible = useSidebarStore((s) => s.setNavItemVisible);
  const setNavItemOrder = useSidebarStore((s) => s.setNavItemOrder);

  // Dragover only moves this local preview. Committing to the store per
  // dragover would serialize it to localStorage and re-render the live
  // sidebar on every pointer move, which made dragging visibly lag; the
  // store commits once on drop and a canceled drag just drops the preview.
  const previewRef = useRef<readonly CustomizableNavItemId[] | null>(null);
  const [previewOrder, setPreviewOrder] = useState<
    readonly CustomizableNavItemId[] | null
  >(null);
  const updatePreview = (order: readonly CustomizableNavItemId[] | null) => {
    previewRef.current = order;
    setPreviewOrder(order);
  };
  // dragover can re-fire for the same source/target pair while the pointer
  // sits on a row boundary; replaying the move would swap the rows back.
  const lastMove = useRef<string | null>(null);

  const items = orderedNavItems(previewOrder ?? navItemOrder).filter(
    ({ id }) => {
      if (id === "loops") return loopsEnabled;
      if (id === "contexts") return bluebirdEnabled;
      if (id === "activity") return bluebirdEnabled && channelsEnabled;
      return true;
    },
  );

  const handleDragStart: DragDropEvents["dragstart"] = () => {
    lastMove.current = null;
    updatePreview(
      orderedNavItems(useSidebarStore.getState().navItemOrder).map(
        (item) => item.id,
      ),
    );
  };

  const handleDragOver: DragDropEvents["dragover"] = (event) => {
    const sourceId = event.operation.source?.id;
    const targetId = event.operation.target?.id;
    const current = previewRef.current;
    if (!current || !sourceId || !targetId || sourceId === targetId) return;
    const moveKey = `${String(sourceId)}->${String(targetId)}`;
    if (lastMove.current === moveKey) return;
    const next = moveNavItem(current, String(sourceId), String(targetId));
    if (next !== current) {
      lastMove.current = moveKey;
      updatePreview(next);
    }
  };

  const handleDragEnd: DragDropEvents["dragend"] = (event) => {
    const preview = previewRef.current;
    updatePreview(null);
    if (event.canceled || !preview) return;
    const stored = orderedNavItems(useSidebarStore.getState().navItemOrder).map(
      (item) => item.id,
    );
    if (sameOrder(stored, preview)) return;
    setNavItemOrder(preview);
    const moved = CUSTOMIZABLE_NAV_ITEMS.find(
      ({ id }) => id === event.operation.source?.id,
    );
    if (!moved) return;
    track(ANALYTICS_EVENTS.SIDEBAR_REORDERED, {
      item: moved.analyticsId,
      to_index: preview.indexOf(moved.id),
    });
  };

  return (
    <Flex direction="column" className="max-w-[360px]">
      <Text className="text-gray-10 text-sm">
        Choose which items appear in your sidebar and drag to reorder.
      </Text>

      {/* Default pointer activation starts a mouse drag from the handle
            immediately; a distance constraint here would delay pickup. */}
      <DragDropProvider
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnd={handleDragEnd}
      >
        <Flex direction="column" gap="3" mt="4">
          {items.map((item, index) => (
            <SortableNavItemRow
              key={item.id}
              item={item}
              index={index}
              visible={isNavItemVisible(navItemOverrides, item.id)}
              onVisibleChange={(nextVisible) => {
                setNavItemVisible(item.id, nextVisible);
                track(ANALYTICS_EVENTS.SIDEBAR_CUSTOMIZED, {
                  item: item.analyticsId,
                  visible: nextVisible,
                });
              }}
            />
          ))}
        </Flex>
      </DragDropProvider>

      <Flex mt="4" justify="start" align="center">
        <Button
          size="1"
          variant="ghost"
          color="gray"
          onClick={() => setNavItemOrder([])}
        >
          Reset
        </Button>
      </Flex>
    </Flex>
  );
}

function SortableNavItemRow({
  item,
  index,
  visible,
  onVisibleChange,
}: {
  item: CustomizableNavItem;
  index: number;
  visible: boolean;
  onVisibleChange: (visible: boolean) => void;
}) {
  const { ref, handleRef, isDragging } = useSortable({
    id: item.id,
    index,
    group: "customize-sidebar-nav",
    transition: { duration: 200, easing: "ease" },
  });
  const ItemIcon = ITEM_ICONS[item.id];
  return (
    <div ref={ref} style={{ opacity: isDragging ? 0.5 : 1 }}>
      <Flex gap="2" align="center">
        <button
          ref={handleRef as RefCallback<HTMLButtonElement>}
          type="button"
          title="Drag to reorder"
          className="shrink-0 cursor-grab text-gray-9 hover:text-gray-11"
        >
          <DotsSixVertical size={14} />
        </button>
        <Text as="label" size="2" className="flex-1">
          <Flex gap="2" align="center">
            <Checkbox
              checked={visible}
              onCheckedChange={(checked) => onVisibleChange(checked === true)}
            />
            <ItemIcon size={16} />
            {item.label}
          </Flex>
        </Text>
      </Flex>
    </div>
  );
}
