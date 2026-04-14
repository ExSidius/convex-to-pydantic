import { mutation } from "../../_generated/server";

export const ship = mutation({
  args: {},
  handler: async () => "shipped",
});
