import { porHoraAGrafico, porMetodoAGrafico, porSedeAGrafico } from './resumen-charts';
import { ResumenAsistencias } from './models';

const resumen: ResumenAsistencias = {
  por_sede: [
    { sede: 'Quito', total: 12 },
    { sede: 'Guayaquil', total: 5 }
  ],
  por_hora: [
    { hora: '2026-09-24T14:00:00Z', total: 3 },
    { hora: '2026-09-24T15:00:00Z', total: 8 }
  ],
  por_metodo: [
    { metodo: 'AUTO', total: 40 },
    { metodo: 'MANUAL', total: 3 }
  ]
};

describe('porSedeAGrafico', () => {
  it('mapea sede/total a name/value', () => {
    expect(porSedeAGrafico(resumen)).toEqual([
      { name: 'Quito', value: 12 },
      { name: 'Guayaquil', value: 5 }
    ]);
  });
});

describe('porMetodoAGrafico', () => {
  it('traduce los códigos de método a etiquetas legibles', () => {
    expect(porMetodoAGrafico(resumen)).toEqual([
      { name: 'Automático', value: 40 },
      { name: 'Manual', value: 3 }
    ]);
  });

  it('deja el código tal cual si no lo reconoce', () => {
    const otro: ResumenAsistencias = { ...resumen, por_metodo: [{ metodo: 'OTRO', total: 1 }] };
    expect(porMetodoAGrafico(otro)).toEqual([{ name: 'OTRO', value: 1 }]);
  });
});

describe('porHoraAGrafico', () => {
  it('envuelve los puntos en una sola serie', () => {
    const grafico = porHoraAGrafico(resumen);
    expect(grafico.length).toBe(1);
    expect(grafico[0].name).toBe('Verificaciones');
    expect(grafico[0].series.length).toBe(2);
    expect(grafico[0].series[0].value).toBe(3);
  });
});
