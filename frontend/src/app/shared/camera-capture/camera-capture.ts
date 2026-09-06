import {
  AfterViewInit,
  Component,
  ElementRef,
  EventEmitter,
  OnDestroy,
  Output,
  ViewChild,
  signal
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-camera-capture',
  standalone: true,
  imports: [MatButtonModule, MatIconModule],
  templateUrl: './camera-capture.html',
  styleUrl: './camera-capture.scss'
})
export class CameraCapture implements AfterViewInit, OnDestroy {
  @Output() capturado = new EventEmitter<Blob>();
  @ViewChild('video') videoRef!: ElementRef<HTMLVideoElement>;
  @ViewChild('canvas') canvasRef!: ElementRef<HTMLCanvasElement>;

  readonly listo = signal(false);
  readonly error = signal<string | null>(null);

  private stream: MediaStream | null = null;

  async ngAfterViewInit(): Promise<void> {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 480, height: 360 }
      });
      this.videoRef.nativeElement.srcObject = this.stream;
      this.listo.set(true);
    } catch (e) {
      this.error.set('No se pudo acceder a la cámara. Revisa los permisos del navegador.');
    }
  }

  capturar(): void {
    const video = this.videoRef.nativeElement;
    const canvas = this.canvasRef.nativeElement;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d')?.drawImage(video, 0, 0);
    canvas.toBlob(
      (blob) => {
        if (blob) this.capturado.emit(blob);
      },
      'image/jpeg',
      0.92
    );
  }

  ngOnDestroy(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
  }
}
