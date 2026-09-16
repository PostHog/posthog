import { DropdownMenu, DropdownMenuContent } from "@posthog/quill";
import {
  FilterMenuTrigger,
  FilterRadioSubMenu,
} from "@posthog/ui/primitives/FilterMenu";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

function SearchableScope(): React.JSX.Element {
  const [scope, setScope] = useState("for-you");
  return (
    <DropdownMenu>
      <FilterMenuTrigger
        active={scope !== "for-you"}
        label="Filter reports"
        dataAttr="story-report-filter"
      />
      <DropdownMenuContent>
        <FilterRadioSubMenu
          label="Scope"
          value={scope}
          defaultValue="for-you"
          onChange={setScope}
          searchPlaceholder="Search users…"
          options={[
            { value: "for-you", label: "For you" },
            { value: "project", label: "Entire project" },
            {
              value: "alex",
              label: "Alex Example",
              searchLabel: "alex@example.com",
            },
            {
              value: "sam",
              label: "Sam Sample",
              searchLabel: "sam@example.com",
            },
            ...Array.from({ length: 30 }, (_, index) => ({
              value: `user-${index}`,
              label: `Example user ${index}`,
              searchLabel: `user-${index}@example.com`,
            })),
          ]}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const meta = {
  title: "Primitives/Filter menu",
  component: SearchableScope,
} satisfies Meta<typeof SearchableScope>;

export default meta;
type Story = StoryObj<typeof meta>;
export const SearchUsers: Story = {};
