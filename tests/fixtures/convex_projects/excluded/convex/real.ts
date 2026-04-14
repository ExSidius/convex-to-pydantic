import { mutation } from "./_generated/server";
import { v } from "convex/values";

export const doThing = mutation({
  args: { name: v.string() },
  handler: async (ctx, args) => ctx.db.insert("things", { name: args.name }),
});
