// Bench fixture: the golden symbols/edges live in expected.json next to this file.
import { readFile } from "fs/promises";

export class Store {
  constructor(path) {
    this.path = path;
  }

  async load() {
    const raw = await readFile(this.path, "utf8");
    const clean = raw.replace(/["']/g, "");
    return JSON.parse(clean);
  }
}

export async function readConfig(path) {
  const store = new Store(path);
  return store.load();
}
