import { mutation, query } from "../_generated/server";
import { v } from "convex/values";

export const list = query({
  args: {},
  handler: async (ctx) => ctx.db.query("messages").collect(),
});

export const send = mutation({
  args: { body: v.string(), author: v.string() },
  handler: async (ctx, args) => ctx.db.insert("messages", args),
});
