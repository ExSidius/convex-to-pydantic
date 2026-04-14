// Reserved filename: must NOT be scanned for extractable functions.
import { httpRouter } from "convex/server";
import { httpAction } from "./_generated/server";

const http = httpRouter();

http.route({
  path: "/ping",
  method: "GET",
  handler: httpAction(async () => new Response("ok")),
});

export default http;
