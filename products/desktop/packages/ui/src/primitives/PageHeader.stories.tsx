import { CloudIcon, FilesIcon } from "@phosphor-icons/react";
import {
  Button,
  ButtonGroup,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@posthog/quill";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderChip,
  PageHeaderDescription,
  PageHeaderFilters,
  PageHeaderHeading,
  PageHeaderNav,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta = {
  title: "Primitives/PageHeader",
  component: PageHeader,
} satisfies Meta<typeof PageHeader>;

export default meta;
type Story = StoryObj<typeof meta>;

/** The Inbox shape: title, description, tab strip with a filter on the right. */
export const WithTabsAndFilters: Story = {
  args: {
    children: (
      <>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>Inbox</PageHeaderTitle>
          </PageHeaderTitleRow>
          <PageHeaderDescription>
            Work done by your agents – pull requests, reports, and live runs.
          </PageHeaderDescription>
        </PageHeaderHeading>
        <PageHeaderNav>
          <Tabs defaultValue="pulls">
            <TabsList variant="line" className="h-auto gap-0.5">
              <TabsTrigger value="pulls" className="gap-1.5 px-2.5 py-2">
                <span className="font-medium text-[13px]">Pull requests</span>
              </TabsTrigger>
              <TabsTrigger value="reports" className="gap-1.5 px-2.5 py-2">
                <span className="font-medium text-[13px]">Reports</span>
              </TabsTrigger>
            </TabsList>
          </Tabs>
          <PageHeaderFilters>
            <Button variant="outline" size="sm">
              Suggested for me
            </Button>
          </PageHeaderFilters>
        </PageHeaderNav>
      </>
    ),
  },
};

/** The Artifacts shape: a count chip beside the title, view switcher on the right. */
export const WithChipAndActions: Story = {
  args: {
    children: (
      <PageHeaderHeading>
        <PageHeaderTitleRow>
          <PageHeaderTitle>Artifacts</PageHeaderTitle>
          <PageHeaderChip icon={<FilesIcon size={12} weight="fill" />}>
            12 items
          </PageHeaderChip>
          <PageHeaderActions>
            <ButtonGroup>
              <Button variant="outline" size="sm">
                List
              </Button>
              <Button variant="outline" size="sm">
                Grid
              </Button>
            </ButtonGroup>
          </PageHeaderActions>
        </PageHeaderTitleRow>
        <PageHeaderDescription>
          Canvases and pull requests from this space's tasks.
        </PageHeaderDescription>
      </PageHeaderHeading>
    ),
  },
};

/** Title only — the minimum a page has to spend. */
export const TitleOnly: Story = {
  args: {
    children: (
      <PageHeaderHeading>
        <PageHeaderTitleRow>
          <PageHeaderTitle>Loops</PageHeaderTitle>
          <PageHeaderChip icon={<CloudIcon size={12} weight="fill" />}>
            Runs entirely in the cloud
          </PageHeaderChip>
        </PageHeaderTitleRow>
      </PageHeaderHeading>
    ),
  },
};
