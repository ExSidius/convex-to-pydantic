import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

export const get = query({
  args: { id: v.id("users") },
  handler: async (ctx, args) => ctx.db.get(args.id),
});

export const update = mutation({
  args: { id: v.id("users"), name: v.string() },
  handler: async (ctx, args) => ctx.db.patch(args.id, { name: args.name }),
});

// Plain helper — not a Convex function. Must NOT appear in extractor output.
export function formatUserName(name: string): string {
  return name.trim();
}
