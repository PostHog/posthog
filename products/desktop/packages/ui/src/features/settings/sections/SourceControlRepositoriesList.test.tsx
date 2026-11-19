import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SourceControlRepositoriesList } from "./SourceControlRepositoriesList";

const repositories = Array.from({ length: 101 }, (_, index) => ({
  provider: "gitlab" as const,
  integrationId: index,
  fullName: `example/project-${index}`,
  url: `https://gitlab.com/example/project-${index}`,
}));

const props = {
  data: {
    connections: [],
    repositories,
    failedConnections: [],
    pendingConnections: [],
  },
  isPending: false,
  isError: false,
  isRefetching: false,
  refetch: vi.fn(),
};

describe("SourceControlRepositoriesList", () => {
  it("bounds repository rows and keeps every page reachable", () => {
    const { rerender } = render(<SourceControlRepositoriesList {...props} />);
    expect(screen.getAllByRole("button", { name: /^Open / })).toHaveLength(50);
    expect(screen.queryByText("example/project-50")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("example/project-50")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getAllByRole("button", { name: /^Open / })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Next" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(screen.getByText("example/project-50")).toBeInTheDocument();
    rerender(
      <SourceControlRepositoriesList
        {...props}
        data={{ ...props.data, repositories: repositories.slice(0, 1) }}
      />,
    );
    expect(screen.getByText("example/project-0")).toBeInTheDocument();
  });

  it.each(["pending", "failed"] as const)(
    "keeps healthy rows visible when another connection is %s",
    (status) => {
      const connection = {
        provider: "github" as const,
        integrationId: 200,
        label: "Example GitHub",
      };
      render(
        <SourceControlRepositoriesList
          {...props}
          data={{
            ...props.data,
            repositories: repositories.slice(0, 1),
            pendingConnections: status === "pending" ? [connection] : [],
            failedConnections: status === "failed" ? [connection] : [],
          }}
        />,
      );
      expect(screen.getByText("example/project-0")).toBeInTheDocument();
      expect(screen.queryByText(/No repositories yet/)).not.toBeInTheDocument();
      expect(
        screen.getByText(
          status === "pending"
            ? /Loading more repositories/
            : /Couldn't load repositories for/,
        ),
      ).toBeInTheDocument();
    },
  );
});
