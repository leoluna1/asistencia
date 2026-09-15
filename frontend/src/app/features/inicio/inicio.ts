import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';

@Component({
  selector: 'app-inicio',
  standalone: true,
  imports: [RouterLink, MatButtonModule, MatCardModule],
  templateUrl: './inicio.html',
  styleUrl: './inicio.scss'
})
export class Inicio {}
