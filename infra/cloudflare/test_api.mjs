// Test parity: legge lo stesso seed usato dal lato Flask e stampa le
// risposte calcolate dalle funzioni pure del Worker (stessa logica delle
// route /api/schedina, /api/community, /api/tracking-records).
// Uso: node test_api.mjs <seed_dir>
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  schedinaPayload, communityLoad, evaluateCommunity, communitySnapshot,
  trackingRecords,
} from "./worker.mjs";

const dir = process.argv[2];
if (!dir) { console.error("manca seed_dir"); process.exit(2); }

const read = (name, fallback) => {
  try { return JSON.parse(readFileSync(join(dir, name), "utf-8")); }
  catch { return fallback; }
};

const state = read("state.json", {});
const community = communityLoad(read("community.json", null));
evaluateCommunity(community, state);
const learning = read("learning.json", { records: [] });

const out = {
  schedina: schedinaPayload(state.schedina || {}),
  community: communitySnapshot(state, community, "ip:test-ip"),
  tracking: {
    tracked: (learning.records || []).length,
    evaluated: trackingRecords(learning).length,
    records: trackingRecords(learning),
  },
};
process.stdout.write(JSON.stringify(out));
