import { query } from "../_generated/server.js";

export const list = query({
  args: {},
  handler: async (ctx) => ctx.db.query("invoices").collect(),
});
