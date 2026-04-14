import { internalMutation, internalQuery } from "../_generated/server";
import { v } from "convex/values";

export const process = internalMutation({
  args: { id: v.id("jobs") },
  handler: async (ctx, args) => ctx.db.delete(args.id),
});

export const fetch = internalQuery({
  args: { id: v.id("jobs") },
  handler: async (ctx, args) => ctx.db.get(args.id),
});
