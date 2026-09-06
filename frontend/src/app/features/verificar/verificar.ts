import { Component, OnDestroy, ViewChild, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { CameraCapture } from '../../shared/camera-capture/camera-capture';
import { AsistenciaService } from '../../core/asistencia.service';
import { ResultadoVerificacion } from '../../core/models';

const INTERVALO_MS = 2500;
const MAX_INTENTOS = 3; // decisión confirmada: reintento automático, luego agente

@Component({
  selector: 'app-verificar',
  standalone: true,
  imports: [
    FormsModule,
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    CameraCapture
  ],
  templateUrl: './verificar.html',
  styleUrl: './verificar.scss'
})
export class Verificar implements OnDestroy {
  @ViewChild(CameraCapture) camara?: CameraCapture;

  sede = '';
  readonly enSesion = signal(false);
  readonly intentos = signal(0);
  readonly resultado = signal<ResultadoVerificacion | null>(null);
  readonly agotado = signal(false);
  readonly verificando = signal(false);

  private intervalo: ReturnType<typeof setInterval> | null = null;

  constructor(private asistencia: AsistenciaService) {}

  iniciar(): void {
    if (!this.sede) return;
    this.resultado.set(null);
    this.agotado.set(false);
    this.intentos.set(0);
    this.enSesion.set(true);
    this.intervalo = setInterval(() => this.pedirCaptura(), INTERVALO_MS);
  }

  private pedirCaptura(): void {
    if (this.verificando()) return; // no solaparse si la anterior sigue en curso
    this.camara?.capturar(); // dispara (capturado) -> onFotoCapturada
  }

  // El template enlaza esto a (capturado) de app-camera-capture.
  onFotoCapturada(blob: Blob): void {
    this.verificar(blob);
  }

  private async verificar(blob: Blob): Promise<void> {
    this.verificando.set(true);
    try {
      const resultado = await this.asistencia.verificar(this.sede, blob);
      this.resultado.set(resultado);
      if (resultado.verificado) {
        this.detener();
        return;
      }
      const intentos = this.intentos() + 1;
      this.intentos.set(intentos);
      if (intentos >= MAX_INTENTOS) {
        this.agotado.set(true);
        this.detener();
      }
    } finally {
      this.verificando.set(false);
    }
  }

  private detener(): void {
    if (this.intervalo) {
      clearInterval(this.intervalo);
      this.intervalo = null;
    }
    this.enSesion.set(false);
  }

  reintentarDesdeElInicio(): void {
    this.iniciar();
  }

  ngOnDestroy(): void {
    if (this.intervalo) clearInterval(this.intervalo);
  }
}
