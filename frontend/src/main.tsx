import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import App from "./App";
import { loadConfig } from "./lib/api";

// Learn the phone address before the first render, so the QR code is right from the start.
loadConfig().finally(() =>
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  ),
);
