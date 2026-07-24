import { Navigate } from "@tanstack/react-router";

export function RouteNotFound() {
  return <Navigate replace to="/code" />;
}
