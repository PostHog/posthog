import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initAnalytics } from "./analytics";
import "./styles.css";

initAnalytics();

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(<App />);
}
