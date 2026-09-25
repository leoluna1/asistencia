import { TestBed } from '@angular/core/testing';
import { InlineMessage } from './inline-message';

describe('InlineMessage', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [InlineMessage]
    }).compileComponents();
  });

  it('usa el ícono de error por defecto', () => {
    const fixture = TestBed.createComponent(InlineMessage);
    expect(fixture.componentInstance.icono).toBe('error_outline');
  });

  it('usa el ícono de éxito cuando tipo es "ok"', () => {
    const fixture = TestBed.createComponent(InlineMessage);
    fixture.componentInstance.tipo = 'ok';
    expect(fixture.componentInstance.icono).toBe('check_circle');
  });

  it('aplica la clase según el tipo', () => {
    const fixture = TestBed.createComponent(InlineMessage);
    fixture.componentInstance.tipo = 'error';
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('p.error')).toBeTruthy();
  });
});
