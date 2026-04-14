// Underscore-prefixed filename: must NOT be scanned.
import { mutation } from "./_generated/server";

// If this were scanned we'd wrongly see a "secret" mutation.
export const secret = mutation({
  args: {},
  handler: async () => "leaked",
});
