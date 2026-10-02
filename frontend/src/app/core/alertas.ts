import { IntentoRepetido } from './models';

const CLAVE = 'asistencia_alertas_revisadas';
const MAX_GUARDADAS = 500; // solo se listan intentos de 24 h: alcanza de sobra

function revisadas(): number[] {
  try {
    return JSON.parse(localStorage.getItem(CLAVE) ?? '[]');
  } catch {
    return [];
  }
}

/** Intentos repetidos que este navegador todavía no marcó como revisados. */
export function alertasPendientes(intentos: IntentoRepetido[]): IntentoRepetido[] {
  const vistas = new Set(revisadas());
  return intentos.filter((i) => !vistas.has(i.id));
}

export function marcarRevisada(id: number): void {
  localStorage.setItem(CLAVE, JSON.stringify([id, ...revisadas()].slice(0, MAX_GUARDADAS)));
}
