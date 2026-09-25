import { Color, ScaleType } from '@swimlane/ngx-charts';
import { ResumenAsistencias } from './models';

/** Paleta institucional para los 3 gráficos del dashboard (navy/dorado/tinta),
 * en vez del esquema de colores default de ngx-charts. */
export const PNE_CHART_SCHEME: Color = {
  name: 'pne',
  selectable: true,
  group: ScaleType.Ordinal,
  domain: ['#16283F', '#B98A2E', '#55647A', '#2E7D32', '#B00020']
};

const ETIQUETAS_METODO: Record<string, string> = {
  AUTO: 'Automático',
  MANUAL: 'Manual'
};

export function porSedeAGrafico(resumen: ResumenAsistencias): { name: string; value: number }[] {
  return resumen.por_sede.map((fila) => ({ name: fila.sede, value: fila.total }));
}

export function porMetodoAGrafico(resumen: ResumenAsistencias): { name: string; value: number }[] {
  return resumen.por_metodo.map((fila) => ({
    name: ETIQUETAS_METODO[fila.metodo] ?? fila.metodo,
    value: fila.total
  }));
}

/** ngx-charts line-chart espera una lista de series (aunque sea una sola). */
export function porHoraAGrafico(
  resumen: ResumenAsistencias
): { name: string; series: { name: string; value: number }[] }[] {
  return [
    {
      name: 'Verificaciones',
      series: resumen.por_hora.map((fila) => ({
        name: new Date(fila.hora).toLocaleTimeString('es-EC', {
          hour: '2-digit',
          minute: '2-digit'
        }),
        value: fila.total
      }))
    }
  ];
}
