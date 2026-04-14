import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  users: defineTable({
    name: v.string(),
    email: v.string(),
  }),
  messages: defineTable({
    body: v.string(),
    author: v.string(),
  }),
  events: defineTable({
    title: v.string(),
    start: v.number(),
  }),
});
