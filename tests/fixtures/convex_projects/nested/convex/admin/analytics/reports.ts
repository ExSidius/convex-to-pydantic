import { action, query } from "../../_generated/server";
import { v } from "convex/values";

export const daily = query({
  args: { date: v.string() },
  handler: async (_ctx, _args) => ({ active: 0 }),
});

export const exportCsv = action({
  args: { from: v.string(), to: v.string() },
  handler: async (_ctx, _args) => "csv-url",
});
