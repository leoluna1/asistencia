import { paramsDeFiltros } from './filtros-asistencia';

describe('paramsDeFiltros', () => {
  it('no agrega ningún param si los filtros están vacíos', () => {
    const params = paramsDeFiltros({});
    expect(params.keys().length).toBe(0);
  });

  it('omite campos vacíos pero incluye los que sí tienen valor', () => {
    const params = paramsDeFiltros({ q: 'maria', desde: '', hasta: '', metodo: '' });
    expect(params.get('q')).toBe('maria');
    expect(params.has('desde')).toBe(false);
    expect(params.has('hasta')).toBe(false);
    expect(params.has('metodo')).toBe(false);
  });

  it('incluye todos los filtros cuando todos tienen valor', () => {
    const params = paramsDeFiltros({
      q: '1710034065',
      desde: '2026-09-24T00:00:00Z',
      hasta: '2026-09-24T23:59:59Z',
      metodo: 'AUTO'
    });
    expect(params.get('q')).toBe('1710034065');
    expect(params.get('desde')).toBe('2026-09-24T00:00:00Z');
    expect(params.get('hasta')).toBe('2026-09-24T23:59:59Z');
    expect(params.get('metodo')).toBe('AUTO');
  });
});
