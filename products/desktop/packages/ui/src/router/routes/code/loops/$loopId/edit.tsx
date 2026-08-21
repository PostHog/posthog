import { createFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createFileRoute("/code/loops/$loopId/edit")({
  component: EditLoopRoute,
});

function EditLoopRoute() {
  const { loopId } = Route.useParams();
  return (
    <Navigate
      replace
      to="/code/loops/$loopId"
      params={{ loopId }}
      search={{ edit: true }}
    />
  );
}
