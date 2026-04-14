import { mutation, query } from "../../_generated/server";
import { v } from "convex/values";

export const list = query({
  args: {},
  handler: async (ctx) => ctx.db.query("events").collect(),
});

export const create = mutation({
  args: { title: v.string(), start: v.number() },
  handler: async (ctx, args) => ctx.db.insert("events", args),
});
