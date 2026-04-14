import { mutation } from "../_generated/server";
import { v } from "convex/values";

export const enqueue = mutation({
  args: { kind: v.string() },
  handler: async (ctx, args) => ctx.db.insert("jobs", { kind: args.kind }),
});
