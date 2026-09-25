import { Component, Input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

/** Mensaje de error/éxito inline, junto al campo o botón al que corresponde
 * (no un toast) — ver decisión de diseño en la sesión de rediseño visual. */
@Component({
  selector: 'app-mensaje',
  standalone: true,
  imports: [MatIconModule],
  templateUrl: './inline-message.html',
  styleUrl: './inline-message.scss'
})
export class InlineMessage {
  @Input() tipo: 'error' | 'ok' = 'error';

  get icono(): string {
    return this.tipo === 'ok' ? 'check_circle' : 'error_outline';
  }
}
