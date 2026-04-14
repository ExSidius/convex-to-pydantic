import { mutation } from "./_generated/server.js";
import { v } from "convex/values";

export const migrate = mutation({
  args: { batchSize: v.number() },
  handler: async (_ctx, _args) => ({ migrated: 0 }),
});
