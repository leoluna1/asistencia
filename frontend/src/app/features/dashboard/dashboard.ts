import { Component, OnDestroy, OnInit, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { BarChartModule, LineChartModule, PieChartModule } from '@swimlane/ngx-charts';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { AsistenciaService } from '../../core/asistencia.service';
import { AuthService } from '../../core/auth.service';
import { primerMensajeDeError } from '../../core/errores';
import { FilaAsistencia, FiltrosAsistencia } from '../../core/models';
import { PNE_CHART_SCHEME, porHoraAGrafico, porMetodoAGrafico, porSedeAGrafico } from '../../core/resumen-charts';
import { InlineMessage } from '../../shared/inline-message/inline-message';

const INTERVALO_POLLING_MS = 4000;
const DEBOUNCE_BUSQUEDA_MS = 300;

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    DatePipe,
    FormsModule,
    BarChartModule,
    LineChartModule,
    PieChartModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatSelectModule,
    MatTableModule,
    InlineMessage
  ],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss'
})
export class Dashboard implements OnInit, OnDestroy {
  readonly filas = signal<FilaAsistencia[]>([]);
  readonly actualizando = signal(false);
  readonly columnas = [
    'foto',
    'nombre',
    'cedula',
    'sede',
    'metodo',
    'hora'
  ];

  // Filtros combinables (búsqueda, rango de fecha, método) — se mandan a la lista,
  // al resumen de gráficos y a la exportación, para que las 3 vistas coincidan.
  q = '';
  desde = '';
  hasta = '';
  metodo: '' | 'AUTO' | 'MANUAL' = '';
  private debounceBusqueda: ReturnType<typeof setTimeout> | null = null;

  readonly esquemaColores = PNE_CHART_SCHEME;
  // ngx-charts no mide bien un contenedor sin [view] explícito (el SVG termina
  // ocupando un alto absurdo) — fijo, no responsive, pero confiable; las 3
  // tarjetas del grid tienen un ancho similar de todas formas.
  readonly vistaGrafico: [number, number] = [320, 220];
  readonly porSede = signal<{ name: string; value: number }[]>([]);
  readonly porMetodo = signal<{ name: string; value: number }[]>([]);
  readonly porHora = signal<{ name: string; series: { name: string; value: number }[] }[]>([]);
  readonly errorResumen = signal<string | null>(null);

  readonly exportando = signal<'csv' | 'pdf' | null>(null);
  readonly errorExportar = signal<string | null>(null);

  cedulaManual = '';
  sedeManual = '';
  readonly enviandoManual = signal(false);
  readonly errorManual = signal<string | null>(null);
  readonly okManual = signal<string | null>(null);

  private intervalo: ReturnType<typeof setInterval> | null = null;

  constructor(
    private asistencia: AsistenciaService,
    readonly auth: AuthService
  ) {}

  ngOnInit(): void {
    this.actualizar();
    this.intervalo = setInterval(() => this.actualizar(), INTERVALO_POLLING_MS);
  }

  ngOnDestroy(): void {
    if (this.intervalo) clearInterval(this.intervalo);
    if (this.debounceBusqueda) clearTimeout(this.debounceBusqueda);
  }

  private get filtrosActuales(): FiltrosAsistencia {
    return { q: this.q, desde: this.desde, hasta: this.hasta, metodo: this.metodo };
  }

  /** La búsqueda de texto espera una pausa al tipear; fecha/método aplican de
   * una — no hace falta debounce en controles que cambian con poca frecuencia. */
  onBusquedaInput(valor: string): void {
    this.q = valor;
    if (this.debounceBusqueda) clearTimeout(this.debounceBusqueda);
    this.debounceBusqueda = setTimeout(() => this.actualizar(), DEBOUNCE_BUSQUEDA_MS);
  }

  aplicarFiltro(): void {
    this.actualizar();
  }

  private async actualizar(): Promise<void> {
    this.actualizando.set(true);
    try {
      this.filas.set(await this.asistencia.listar(this.filtrosActuales));
    } catch {
      // ponytail: si falla un polling, se reintenta solo en el próximo tick — no
      // hace falta mostrar un error por un fallo aislado de red.
    } finally {
      this.actualizando.set(false);
    }
    // Los gráficos son independientes de la tabla: si el resumen falla, la
    // tabla sigue funcionando igual (y viceversa).
    try {
      const resumen = await this.asistencia.resumen(this.filtrosActuales);
      this.porSede.set(porSedeAGrafico(resumen));
      this.porMetodo.set(porMetodoAGrafico(resumen));
      this.porHora.set(porHoraAGrafico(resumen));
      this.errorResumen.set(null);
    } catch {
      this.errorResumen.set('No se pudieron cargar los gráficos.');
    }
  }

  async exportar(formato: 'csv' | 'pdf'): Promise<void> {
    this.exportando.set(formato);
    this.errorExportar.set(null);
    try {
      const blob = await this.asistencia.exportar(formato, this.filtrosActuales);
      this.descargarBlob(blob, `asistencias.${formato}`);
    } catch {
      this.errorExportar.set('No se pudo generar el archivo.');
    } finally {
      this.exportando.set(null);
    }
  }

  private descargarBlob(blob: Blob, nombreArchivo: string): void {
    const url = URL.createObjectURL(blob);
    const enlace = document.createElement('a');
    enlace.href = url;
    enlace.download = nombreArchivo;
    enlace.click();
    URL.revokeObjectURL(url);
  }

  async forzarManual(): Promise<void> {
    if (!this.cedulaManual || !this.sedeManual) return;
    this.enviandoManual.set(true);
    this.errorManual.set(null);
    this.okManual.set(null);
    try {
      const resultado = await this.asistencia.forzarManual(this.cedulaManual, this.sedeManual);
      this.okManual.set(
        `Asistencia forzada para ${resultado.postulante.nombres} ${resultado.postulante.apellidos}.`
      );
      this.cedulaManual = '';
      this.actualizar();
    } catch (e: any) {
      this.errorManual.set(primerMensajeDeError(e?.error) || 'No se pudo forzar la asistencia.');
    } finally {
      this.enviandoManual.set(false);
    }
  }
}
