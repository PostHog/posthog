import { createFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createFileRoute("/loops/$loopId/edit")({
  component: EditLoopRoute,
});

function EditLoopRoute() {
  const { loopId } = Route.useParams();
  return (
    <Navigate
      replace
      to="/loops/$loopId"
      params={{ loopId }}
      search={{ edit: true }}
    />
  );
}
