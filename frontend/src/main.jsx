import React from "react";
import { createRoot } from "react-dom/client";
import Identity from "./Identity";
import "./styles.css";
createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Identity />
  </React.StrictMode>,
);
