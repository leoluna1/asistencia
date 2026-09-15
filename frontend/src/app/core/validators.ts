// Mismo algoritmo que backend/asistencia/validators.py (módulo 10, coeficientes del
// INEC) — feedback inmediato mientras se escribe, el backend sigue siendo la
// validación real al enviar el formulario.
const COEFICIENTES = [2, 1, 2, 1, 2, 1, 2, 1, 2];

export function cedulaEcuatorianaValida(cedula: string): boolean {
  if (!/^\d{10}$/.test(cedula)) return false;

  const provincia = Number(cedula.slice(0, 2));
  const tercerDigito = Number(cedula[2]);
  if (provincia < 1 || provincia > 24 || tercerDigito >= 6) return false;

  let total = 0;
  for (let i = 0; i < 9; i++) {
    const producto = Number(cedula[i]) * COEFICIENTES[i];
    total += producto > 9 ? producto - 9 : producto;
  }

  const verificador = (10 - (total % 10)) % 10;
  return verificador === Number(cedula[9]);
}

/** Deja solo dígitos y corta al largo máximo — para inputs de cédula/teléfono. */
export function soloDigitos(valor: string, largoMaximo: number): string {
  return valor.replace(/\D/g, '').slice(0, largoMaximo);
}
