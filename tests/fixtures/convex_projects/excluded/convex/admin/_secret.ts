// Underscore-prefixed in a nested dir: must NOT be scanned.
import { mutation } from "../_generated/server";

export const bypass = mutation({
  args: {},
  handler: async () => "leaked",
});
