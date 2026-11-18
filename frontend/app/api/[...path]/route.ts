/**
 * Same-origin proxy to the FastAPI backend. The browser only ever talks to the Next.js server, so no CORS setup
 * is needed and the backend address (API_INTERNAL_URL) is read at runtime rather than baked into the build.
 */
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const API = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");
const HOP_BY_HOP = new Set(["connection", "keep-alive", "transfer-encoding", "upgrade", "content-encoding", "host"]);

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const target = `${API}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key) && key !== "content-length") headers.set(key, value);
  });
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer(),
      cache: "no-store",
      redirect: "manual",
    });
  } catch (err) {
    return Response.json({ detail: `TerraProof API unreachable at ${API}: ${(err as Error).message}` }, { status: 502 });
  }
  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key)) out.set(key, value);
  });
  // fetch() transparently decompresses; a stale length would truncate the body.
  if (upstream.headers.has("content-encoding")) out.delete("content-length");
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE, proxy as PATCH };
