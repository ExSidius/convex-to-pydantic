import { action } from "../../_generated/server";
import { v } from "convex/values";

export const stripe = action({
  args: { payload: v.string() },
  handler: async (_ctx, _args) => ({ ok: true }),
});
