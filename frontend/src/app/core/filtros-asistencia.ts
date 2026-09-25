import { HttpParams } from '@angular/common/http';
import { FiltrosAsistencia } from './models';

/** Arma los query params de HttpClient a partir de los filtros del dashboard,
 * omitiendo los que están vacíos (evita mandar "?q=&desde=&metodo=" al backend). */
export function paramsDeFiltros(filtros: FiltrosAsistencia): HttpParams {
  let params = new HttpParams();
  if (filtros.q) params = params.set('q', filtros.q);
  if (filtros.desde) params = params.set('desde', filtros.desde);
  if (filtros.hasta) params = params.set('hasta', filtros.hasta);
  if (filtros.metodo) params = params.set('metodo', filtros.metodo);
  return params;
}
