// Copyright (c) 2026 Roman Sutormin. MIT License.

import { defineConfig } from "vite";

export default defineConfig({
  base: process.env.GITHUB_ACTIONS ? "/YourBestPlaceToLive/" : "/",
  server: {
    port: 5173,
  },
});
