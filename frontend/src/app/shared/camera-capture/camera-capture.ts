import {
  AfterViewInit,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnDestroy,
  Output,
  ViewChild,
  signal
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { PostulantesService } from '../../core/postulantes.service';

@Component({
  selector: 'app-camera-capture',
  standalone: true,
  imports: [MatButtonModule, MatIconModule],
  templateUrl: './camera-capture.html',
  styleUrl: './camera-capture.scss'
})
export class CameraCapture implements AfterViewInit, OnDestroy {
  // Solo el registro (ver ProbarEncuadreView) necesita el sondeo en vivo con aviso
  // de encuadre + captura automática. Verificar dispara su propio ciclo de captura
  // (reintentos cada 2.5s vía capturar()) y no debe pedir este chequeo extra.
  @Input() sondeoEnVivo = false;
  @Output() capturado = new EventEmitter<Blob>();
  @ViewChild('video') videoRef!: ElementRef<HTMLVideoElement>;
  @ViewChild('canvas') canvasRef!: ElementRef<HTMLCanvasElement>;

  readonly listo = signal(false);
  readonly error = signal<string | null>(null);
  readonly aviso = signal<string | null>(null);
  readonly capturando = signal(false);

  private stream: MediaStream | null = null;
  private temporizador: ReturnType<typeof setInterval> | null = null;
  private sondeando = false;
  private esperaCaptura: ReturnType<typeof setTimeout> | null = null;

  constructor(private postulantes: PostulantesService) {}

  async ngAfterViewInit(): Promise<void> {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 480, height: 360 }
      });
      this.videoRef.nativeElement.srcObject = this.stream;
      this.listo.set(true);
      if (this.sondeoEnVivo) this.iniciarSondeo();
    } catch (e) {
      this.error.set('No se pudo acceder a la cámara. Revisa los permisos del navegador.');
    }
  }

  // Cada ~900ms manda el frame actual al mismo chequeo que corre en el registro real
  // (ver ProbarEncuadreView) — cuando dice "ok", ese frame ya es válido y se usa tal
  // cual como la captura final, sin volver a tomar la foto.
  private iniciarSondeo(): void {
    this.temporizador = setInterval(() => this.sondear(), 900);
  }

  private async sondear(): Promise<void> {
    if (this.sondeando) return;
    this.sondeando = true;
    try {
      const frame = await this.capturarFrame();
      if (!frame || !this.temporizador) return;

      const resultado = await this.postulantes.probarEncuadre(frame);
      if (!this.temporizador) return;

      if (resultado.ok) {
        this.detenerSondeo();
        // Pausa breve mostrando "no te muevas" antes de emitir: sin esto, la
        // persona seguía acomodándose justo cuando el frame ya se había tomado.
        this.capturando.set(true);
        this.esperaCaptura = setTimeout(() => this.capturado.emit(frame), 700);
      } else {
        this.aviso.set(resultado.motivo ?? null);
      }
    } catch {
      // Falla de red puntual del sondeo: se ignora, el próximo intento en ~900ms sigue.
    } finally {
      this.sondeando = false;
    }
  }

  private detenerSondeo(): void {
    if (this.temporizador) {
      clearInterval(this.temporizador);
      this.temporizador = null;
    }
  }

  private capturarFrame(): Promise<Blob | null> {
    const video = this.videoRef.nativeElement;
    const canvas = this.canvasRef.nativeElement;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d')?.drawImage(video, 0, 0);
    return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
  }

  /** Captura inmediata sin pasar por el sondeo — la usa Verificar en su propio ciclo. */
  capturar(): void {
    this.capturarFrame().then((frame) => {
      if (frame) this.capturado.emit(frame);
    });
  }

  /** Botón manual del registro: corta el sondeo y usa el frame actual tal cual esté. */
  capturarAhora(): void {
    this.detenerSondeo();
    this.capturar();
  }

  ngOnDestroy(): void {
    this.detenerSondeo();
    if (this.esperaCaptura) clearTimeout(this.esperaCaptura);
    this.stream?.getTracks().forEach((track) => track.stop());
  }
}
