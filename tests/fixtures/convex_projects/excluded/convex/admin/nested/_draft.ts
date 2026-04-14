// Underscore file in deeply-nested dir: must NOT be scanned.
import { mutation } from "../../_generated/server";

export const stub = mutation({
  args: {},
  handler: async () => "leaked",
});
