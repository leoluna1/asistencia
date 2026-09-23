import { Component, OnDestroy, OnInit, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatTableModule } from '@angular/material/table';
import { AsistenciaService } from '../../core/asistencia.service';
import { AuthService } from '../../core/auth.service';
import { primerMensajeDeError } from '../../core/errores';
import { FilaAsistencia } from '../../core/models';

const INTERVALO_POLLING_MS = 4000;

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    DatePipe,
    FormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatTableModule
  ],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss'
})
export class Dashboard implements OnInit, OnDestroy {
  readonly filas = signal<FilaAsistencia[]>([]);
  readonly columnas = [
    'foto',
    'nombre',
    'cedula',
    'sede',
    'metodo',
    'hora'
  ];

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
  }

  private async actualizar(): Promise<void> {
    try {
      this.filas.set(await this.asistencia.listar());
    } catch {
      // ponytail: si falla un polling, se reintenta solo en el próximo tick — no
      // hace falta mostrar un error por un fallo aislado de red.
    }
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
