import { mutation } from "../_generated/server";
import { v } from "convex/values";

// Shares file name with convex/users.ts at the root — must be disambiguated
// via module path (`admin/users` vs `users`).
export const ban = mutation({
  args: { userId: v.id("users") },
  handler: async (ctx, args) => ctx.db.delete(args.userId),
});
