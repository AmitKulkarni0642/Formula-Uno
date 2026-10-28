import type { Circuit } from "./types";

/** Maps an event name (from /schedule) to a registered circuit key (for /predict/*), or null if this event has no trained model. */
export function findCircuitKey(circuits: Circuit[], eventName: string): string | null {
  return circuits.find((c) => c.event === eventName)?.key ?? null;
}
