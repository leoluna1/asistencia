import { asegurarLocalStorage } from './testing-storage';
import { alertasPendientes, marcarRevisada } from './alertas';
import { IntentoRepetido } from './models';

asegurarLocalStorage();

const intento = (id: number): IntentoRepetido => ({
  id, cedula: '1710034065', nombres: 'Juan', apellidos: 'Pérez', sede: 'Guayaquil',
  intentado_en: '2026-10-01T09:00:00-05:00', sede_original: 'Quito',
  primera_asistencia: '2026-10-01T08:42:00-05:00'
});

describe('alertas de intento repetido', () => {
  beforeEach(() => localStorage.clear());

  it('muestra todas mientras ninguna fue revisada', () => {
    expect(alertasPendientes([intento(1), intento(2)]).map((i) => i.id)).toEqual([1, 2]);
  });

  it('una alerta marcada como revisada deja de mostrarse y queda así al recargar', () => {
    marcarRevisada(1);
    expect(alertasPendientes([intento(1), intento(2)]).map((i) => i.id)).toEqual([2]);
  });
});
