import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { API_BASE_URL } from './api-base';
import { paramsDeFiltros } from './filtros-asistencia';
import {
  FilaAsistencia,
  FiltrosAsistencia,
  ResultadoManual,
  ResultadoVerificacion,
  ResumenAsistencias
} from './models';

@Injectable({ providedIn: 'root' })
export class AsistenciaService {
  constructor(private http: HttpClient) {}

  verificar(sede: string, foto: Blob): Promise<ResultadoVerificacion> {
    const form = new FormData();
    form.append('sede', sede);
    form.append('foto', foto, 'foto.jpg');
    return firstValueFrom(
      this.http.post<ResultadoVerificacion>(`${API_BASE_URL}/verificar/`, form)
    );
  }

  forzarManual(cedula: string, sede: string): Promise<ResultadoManual> {
    const form = new FormData();
    form.append('cedula', cedula);
    form.append('sede', sede);
    return firstValueFrom(
      this.http.post<ResultadoManual>(`${API_BASE_URL}/asistencia/manual/`, form)
    );
  }

  async listar(filtros: FiltrosAsistencia = {}): Promise<FilaAsistencia[]> {
    // El listado está paginado (miles de postulantes) — el dashboard solo pide la
    // primera página, la más reciente, que es lo único que importa en un panel en vivo.
    const pagina = await firstValueFrom(
      this.http.get<{ results: FilaAsistencia[] }>(`${API_BASE_URL}/asistencias/`, {
        params: paramsDeFiltros(filtros)
      })
    );
    return pagina.results;
  }

  resumen(filtros: FiltrosAsistencia = {}): Promise<ResumenAsistencias> {
    return firstValueFrom(
      this.http.get<ResumenAsistencias>(`${API_BASE_URL}/asistencias/resumen/`, {
        params: paramsDeFiltros(filtros)
      })
    );
  }

  exportar(formato: 'csv' | 'pdf', filtros: FiltrosAsistencia = {}): Promise<Blob> {
    return firstValueFrom(
      this.http.get(`${API_BASE_URL}/asistencias/exportar/`, {
        params: paramsDeFiltros(filtros).set('formato', formato),
        responseType: 'blob'
      })
    );
  }
}
