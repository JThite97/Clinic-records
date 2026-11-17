import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter } from "react-router-dom";
import App from "./App";
import { initApi } from "./api";
import "./styles.css";

const root = ReactDOM.createRoot(document.getElementById("root")!);

initApi()
  .catch((e) => console.error("API init failed", e))
  .finally(() => {
    root.render(
      <React.StrictMode>
        <HashRouter>
          <App />
        </HashRouter>
      </React.StrictMode>,
    );
  });
