import { query } from "../../_generated/server.js";

export const snapshot = query({
  args: {},
  handler: async (_ctx) => ({ version: 1 }),
});
