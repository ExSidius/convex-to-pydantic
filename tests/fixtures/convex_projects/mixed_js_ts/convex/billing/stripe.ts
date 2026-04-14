import { action } from "../_generated/server";
import { v } from "convex/values";

export const checkout = action({
  args: { priceId: v.string() },
  handler: async (_ctx, _args) => ({ url: "https://example.com" }),
});
