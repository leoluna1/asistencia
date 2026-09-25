import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';

@Component({
  selector: 'app-inicio',
  standalone: true,
  imports: [RouterLink, MatButtonModule],
  templateUrl: './inicio.html',
  styleUrl: './inicio.scss'
})
export class Inicio {}
