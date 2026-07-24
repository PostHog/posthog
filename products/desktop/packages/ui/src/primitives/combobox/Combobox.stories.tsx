import { Plus } from "@phosphor-icons/react";
import { Combobox } from "@posthog/ui/primitives/combobox/Combobox";
import { Button, Text } from "@radix-ui/themes";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

const meta: Meta = {
  title: "Components/UI/Combobox",
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj;

const fruits = [
  { value: "apple", label: "Apple" },
  { value: "banana", label: "Banana" },
  { value: "cherry", label: "Cherry" },
  { value: "date", label: "Date" },
  { value: "elderberry", label: "Elderberry" },
];

const tropicalFruits = [
  { value: "mango", label: "Mango" },
  { value: "papaya", label: "Papaya" },
  { value: "pineapple", label: "Pineapple" },
  { value: "dragonfruit", label: "Dragon Fruit" },
];

const citrusFruits = [
  { value: "orange", label: "Orange" },
  { value: "lemon", label: "Lemon" },
  { value: "lime", label: "Lime" },
  { value: "grapefruit", label: "Grapefruit" },
];

const berriesFruits = [
  { value: "strawberry", label: "Strawberry" },
  { value: "blueberry", label: "Blueberry" },
  { value: "raspberry", label: "Raspberry" },
  { value: "blackberry", label: "Blackberry" },
];

export const Basic: Story = {
  render: () => {
    const [value, setValue] = useState("");

    return (
      <Combobox.Root value={value} onValueChange={setValue}>
        <Combobox.Trigger placeholder="Select a fruit..." />
        <Combobox.Content>
          {fruits.map((fruit) => (
            <Combobox.Item key={fruit.value} value={fruit.value}>
              {fruit.label}
            </Combobox.Item>
          ))}
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const WithSearch: Story = {
  render: () => {
    const [value, setValue] = useState("");

    const allFruits = [...tropicalFruits, ...citrusFruits, ...berriesFruits];

    return (
      <Combobox.Root value={value} onValueChange={setValue}>
        <Combobox.Trigger placeholder="Search fruits..." />
        <Combobox.Content>
          <Combobox.Input placeholder="Search..." />
          <Combobox.Empty>No fruits found.</Combobox.Empty>
          {allFruits.map((fruit) => (
            <Combobox.Item key={fruit.value} value={fruit.value}>
              {fruit.label}
            </Combobox.Item>
          ))}
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const WithGroups: Story = {
  render: () => {
    const [value, setValue] = useState("");

    return (
      <Combobox.Root value={value} onValueChange={setValue}>
        <Combobox.Trigger placeholder="Select a fruit..." />
        <Combobox.Content>
          <Combobox.Group heading="Tropical">
            {tropicalFruits.map((fruit) => (
              <Combobox.Item key={fruit.value} value={fruit.value}>
                {fruit.label}
              </Combobox.Item>
            ))}
          </Combobox.Group>

          <Combobox.Separator />

          <Combobox.Group heading="Citrus">
            {citrusFruits.map((fruit) => (
              <Combobox.Item key={fruit.value} value={fruit.value}>
                {fruit.label}
              </Combobox.Item>
            ))}
          </Combobox.Group>

          <Combobox.Separator />

          <Combobox.Group heading="Berries">
            {berriesFruits.map((fruit) => (
              <Combobox.Item key={fruit.value} value={fruit.value}>
                {fruit.label}
              </Combobox.Item>
            ))}
          </Combobox.Group>
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const WithFooter: Story = {
  render: () => {
    const [value, setValue] = useState("");

    const allFruits = [...tropicalFruits, ...citrusFruits, ...berriesFruits];

    return (
      <Combobox.Root value={value} onValueChange={setValue}>
        <Combobox.Trigger placeholder="Select a fruit..." />
        <Combobox.Content>
          {allFruits.map((fruit) => (
            <Combobox.Item key={fruit.value} value={fruit.value}>
              {fruit.label}
            </Combobox.Item>
          ))}
          <Combobox.Footer>
            <Button variant="ghost" size="1" className="w-full">
              <Plus weight="bold" />
              Add fruit
            </Button>
          </Combobox.Footer>
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const FullFeatured: Story = {
  render: () => {
    const [value, setValue] = useState("");

    return (
      <Combobox.Root value={value} onValueChange={setValue}>
        <Combobox.Trigger placeholder="Search fruits..." />
        <Combobox.Content>
          <Combobox.Input placeholder="Type to search..." />
          <Combobox.Empty>No fruits found.</Combobox.Empty>

          <Combobox.Group heading="Tropical">
            {tropicalFruits.map((fruit) => (
              <Combobox.Item key={fruit.value} value={fruit.value}>
                {fruit.label}
              </Combobox.Item>
            ))}
          </Combobox.Group>

          <Combobox.Separator />

          <Combobox.Group heading="Citrus">
            {citrusFruits.map((fruit) => (
              <Combobox.Item key={fruit.value} value={fruit.value}>
                {fruit.label}
              </Combobox.Item>
            ))}
          </Combobox.Group>

          <Combobox.Separator />

          <Combobox.Group heading="Berries">
            {berriesFruits.map((fruit) => (
              <Combobox.Item key={fruit.value} value={fruit.value}>
                {fruit.label}
              </Combobox.Item>
            ))}
          </Combobox.Group>

          <Combobox.Footer>
            <Button variant="ghost" size="1" className="w-full">
              <Plus weight="bold" />
              Add fruit
            </Button>
          </Combobox.Footer>
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const GhostVariant: Story = {
  render: () => {
    const [value, setValue] = useState("");

    return (
      <Combobox.Root value={value} onValueChange={setValue} size="1">
        <Combobox.Trigger variant="ghost" placeholder="Select..." />
        <Combobox.Content>
          {fruits.map((fruit) => (
            <Combobox.Item key={fruit.value} value={fruit.value}>
              {fruit.label}
            </Combobox.Item>
          ))}
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const SurfaceVariant: Story = {
  render: () => {
    const [value, setValue] = useState("");

    return (
      <Combobox.Root value={value} onValueChange={setValue} size="2">
        <Combobox.Trigger variant="surface" placeholder="Select a fruit..." />
        <Combobox.Content>
          {fruits.map((fruit) => (
            <Combobox.Item key={fruit.value} value={fruit.value}>
              {fruit.label}
            </Combobox.Item>
          ))}
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const SoftVariant: Story = {
  render: () => {
    const [value, setValue] = useState("");

    return (
      <Combobox.Root value={value} onValueChange={setValue} size="2">
        <Combobox.Trigger variant="soft" placeholder="Select a fruit..." />
        <Combobox.Content>
          {fruits.map((fruit) => (
            <Combobox.Item key={fruit.value} value={fruit.value}>
              {fruit.label}
            </Combobox.Item>
          ))}
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const ClassicVariant: Story = {
  render: () => {
    const [value, setValue] = useState("");

    return (
      <Combobox.Root value={value} onValueChange={setValue} size="2">
        <Combobox.Trigger variant="classic" placeholder="Select a fruit..." />
        <Combobox.Content>
          {fruits.map((fruit) => (
            <Combobox.Item key={fruit.value} value={fruit.value}>
              {fruit.label}
            </Combobox.Item>
          ))}
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const Disabled: Story = {
  render: () => {
    const [value, setValue] = useState("apple");

    return (
      <Combobox.Root value={value} onValueChange={setValue} disabled>
        <Combobox.Trigger placeholder="Select a fruit..." />
        <Combobox.Content>
          {fruits.map((fruit) => (
            <Combobox.Item key={fruit.value} value={fruit.value}>
              {fruit.label}
            </Combobox.Item>
          ))}
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const DisabledItems: Story = {
  render: () => {
    const [value, setValue] = useState("");

    return (
      <Combobox.Root value={value} onValueChange={setValue}>
        <Combobox.Trigger placeholder="Select a fruit..." />
        <Combobox.Content>
          <Combobox.Item value="apple">Apple</Combobox.Item>
          <Combobox.Item value="banana" disabled>
            Banana (out of stock)
          </Combobox.Item>
          <Combobox.Item value="cherry">Cherry</Combobox.Item>
          <Combobox.Item value="date" disabled>
            Date (out of stock)
          </Combobox.Item>
          <Combobox.Item value="elderberry">Elderberry</Combobox.Item>
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const EmptyState: Story = {
  render: () => {
    const [value, setValue] = useState("");

    return (
      <Combobox.Root value={value} onValueChange={setValue}>
        <Combobox.Trigger placeholder="Search fruits..." />
        <Combobox.Content>
          <Combobox.Input placeholder="Type to search..." />
          <Combobox.Empty>No fruits match your search.</Combobox.Empty>
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const FilteredContent: Story = {
  render: () => {
    const [value, setValue] = useState("");
    const allFruits = [...fruits, ...tropicalFruits, ...citrusFruits];

    return (
      <Combobox.Root value={value} onValueChange={setValue}>
        <Combobox.Trigger placeholder="Search fruits..." />
        <Combobox.Content items={allFruits} getValue={(f) => f.label} limit={5}>
          {({ filtered, hasMore, moreCount }) => (
            <>
              <Combobox.Input placeholder="Type to search..." />
              <Combobox.Empty>No fruits found.</Combobox.Empty>
              {filtered.map((fruit) => (
                <Combobox.Item key={fruit.value} value={fruit.value}>
                  {fruit.label}
                </Combobox.Item>
              ))}
              {hasMore && (
                <div className="combobox-label">
                  {moreCount} more — type to filter
                </div>
              )}
            </>
          )}
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

const skills = [
  {
    value: "investigate-metric",
    label: "investigate-metric",
    description: "Diagnose why a metric moved and surface the drivers.",
  },
  {
    value: "querying-posthog-data",
    label: "querying-posthog-data",
    description: "Write and run HogQL against the project's event data.",
  },
  {
    value: "creating-experiments",
    label: "creating-experiments",
    description:
      "Define a hypothesis, configure rollout, and set up analytics for an A/B test.",
  },
  {
    value: "investigating-replay",
    label: "investigating-replay",
    description: "Find and watch session replays relevant to an issue.",
  },
];

export const WithDescriptions: Story = {
  render: () => {
    const [value, setValue] = useState("");

    return (
      <Combobox.Root value={value} onValueChange={setValue} size="2">
        <Combobox.Trigger placeholder="Pick a skill..." className="w-[280px]" />
        <Combobox.Content
          items={skills}
          getValue={(s) => `${s.label} ${s.description}`}
        >
          {({ filtered, hasMore, moreCount }) => (
            <>
              <Combobox.Input placeholder="Search skills..." />
              <Combobox.Empty>No matching skills</Combobox.Empty>
              {filtered.map((skill) => (
                <Combobox.Item
                  key={skill.value}
                  value={skill.value}
                  textValue={skill.label}
                  description={skill.description}
                >
                  {skill.label}
                </Combobox.Item>
              ))}
              {hasMore && (
                <Combobox.Label>
                  {moreCount} more; type to filter
                </Combobox.Label>
              )}
            </>
          )}
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const ControlledSearch: Story = {
  render: () => {
    const [value, setValue] = useState("");
    const [searchQuery, setSearchQuery] = useState("");

    const filteredFruits = fruits.filter((fruit) =>
      fruit.label.toLowerCase().includes(searchQuery.toLowerCase()),
    );

    return (
      <Combobox.Root value={value} onValueChange={setValue}>
        <Combobox.Trigger placeholder="Search fruits..." />
        <Combobox.Content shouldFilter={false}>
          <Combobox.Input
            placeholder="Type to search..."
            value={searchQuery}
            onValueChange={setSearchQuery}
          />
          <Combobox.Empty>No fruits found.</Combobox.Empty>
          {filteredFruits.map((fruit) => (
            <Combobox.Item key={fruit.value} value={fruit.value}>
              {fruit.label}
            </Combobox.Item>
          ))}
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const SolidContentVariant: Story = {
  render: () => {
    const [value, setValue] = useState("");

    return (
      <Combobox.Root value={value} onValueChange={setValue}>
        <Combobox.Trigger placeholder="Select a fruit..." />
        <Combobox.Content variant="solid">
          {fruits.map((fruit) => (
            <Combobox.Item key={fruit.value} value={fruit.value}>
              {fruit.label}
            </Combobox.Item>
          ))}
        </Combobox.Content>
      </Combobox.Root>
    );
  },
};

export const AllSizes: Story = {
  render: () => {
    const [value1, setValue1] = useState("");
    const [value2, setValue2] = useState("");
    const [value3, setValue3] = useState("");

    return (
      <div className="flex flex-col gap-[24px]">
        <div>
          <Text mb="2" color="gray" className="text-[13px]">
            Size 1
          </Text>
          <Combobox.Root value={value1} onValueChange={setValue1} size="1">
            <Combobox.Trigger placeholder="Search fruits..." />
            <Combobox.Content>
              <Combobox.Input placeholder="Type to search..." />
              <Combobox.Empty>No fruits found.</Combobox.Empty>

              <Combobox.Group heading="Tropical">
                {tropicalFruits.map((fruit) => (
                  <Combobox.Item key={fruit.value} value={fruit.value}>
                    {fruit.label}
                  </Combobox.Item>
                ))}
              </Combobox.Group>

              <Combobox.Separator />

              <Combobox.Group heading="Citrus">
                {citrusFruits.map((fruit) => (
                  <Combobox.Item key={fruit.value} value={fruit.value}>
                    {fruit.label}
                  </Combobox.Item>
                ))}
              </Combobox.Group>

              <Combobox.Separator />

              <Combobox.Group heading="Berries">
                {berriesFruits.map((fruit) => (
                  <Combobox.Item key={fruit.value} value={fruit.value}>
                    {fruit.label}
                  </Combobox.Item>
                ))}
              </Combobox.Group>

              <Combobox.Footer>
                <Button variant="ghost" size="1" className="w-full">
                  <Plus weight="bold" />
                  Add fruit
                </Button>
              </Combobox.Footer>
            </Combobox.Content>
          </Combobox.Root>
        </div>

        <div>
          <Text mb="2" color="gray" className="text-[13px]">
            Size 2
          </Text>
          <Combobox.Root value={value2} onValueChange={setValue2} size="2">
            <Combobox.Trigger placeholder="Search fruits..." />
            <Combobox.Content>
              <Combobox.Input placeholder="Type to search..." />
              <Combobox.Empty>No fruits found.</Combobox.Empty>

              <Combobox.Group heading="Tropical">
                {tropicalFruits.map((fruit) => (
                  <Combobox.Item key={fruit.value} value={fruit.value}>
                    {fruit.label}
                  </Combobox.Item>
                ))}
              </Combobox.Group>

              <Combobox.Separator />

              <Combobox.Group heading="Citrus">
                {citrusFruits.map((fruit) => (
                  <Combobox.Item key={fruit.value} value={fruit.value}>
                    {fruit.label}
                  </Combobox.Item>
                ))}
              </Combobox.Group>

              <Combobox.Separator />

              <Combobox.Group heading="Berries">
                {berriesFruits.map((fruit) => (
                  <Combobox.Item key={fruit.value} value={fruit.value}>
                    {fruit.label}
                  </Combobox.Item>
                ))}
              </Combobox.Group>

              <Combobox.Footer>
                <Button variant="ghost" size="1" className="w-full">
                  <Plus weight="bold" />
                  Add fruit
                </Button>
              </Combobox.Footer>
            </Combobox.Content>
          </Combobox.Root>
        </div>

        <div>
          <Text mb="2" color="gray" className="text-[13px]">
            Size 3
          </Text>
          <Combobox.Root value={value3} onValueChange={setValue3} size="3">
            <Combobox.Trigger placeholder="Search fruits..." />
            <Combobox.Content>
              <Combobox.Input placeholder="Type to search..." />
              <Combobox.Empty>No fruits found.</Combobox.Empty>

              <Combobox.Group heading="Tropical">
                {tropicalFruits.map((fruit) => (
                  <Combobox.Item key={fruit.value} value={fruit.value}>
                    {fruit.label}
                  </Combobox.Item>
                ))}
              </Combobox.Group>

              <Combobox.Separator />

              <Combobox.Group heading="Citrus">
                {citrusFruits.map((fruit) => (
                  <Combobox.Item key={fruit.value} value={fruit.value}>
                    {fruit.label}
                  </Combobox.Item>
                ))}
              </Combobox.Group>

              <Combobox.Separator />

              <Combobox.Group heading="Berries">
                {berriesFruits.map((fruit) => (
                  <Combobox.Item key={fruit.value} value={fruit.value}>
                    {fruit.label}
                  </Combobox.Item>
                ))}
              </Combobox.Group>

              <Combobox.Footer>
                <Button variant="ghost" size="1" className="w-full">
                  <Plus weight="bold" />
                  Add fruit
                </Button>
              </Combobox.Footer>
            </Combobox.Content>
          </Combobox.Root>
        </div>
      </div>
    );
  },
};
