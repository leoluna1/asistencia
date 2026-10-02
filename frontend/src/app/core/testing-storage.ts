// Node 26 define un `localStorage` global que vale undefined sin
// --localstorage-file y tapa al de jsdom en los tests. Solo para specs.
export function asegurarLocalStorage(): void {
  if (typeof localStorage !== 'undefined') return;
  const datos = new Map<string, string>();
  const storage = {
    getItem: (k: string) => datos.get(k) ?? null,
    setItem: (k: string, v: string) => void datos.set(k, String(v)),
    removeItem: (k: string) => void datos.delete(k),
    clear: () => datos.clear(),
    key: (i: number) => [...datos.keys()][i] ?? null,
    get length() {
      return datos.size;
    }
  };
  Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true });
}
