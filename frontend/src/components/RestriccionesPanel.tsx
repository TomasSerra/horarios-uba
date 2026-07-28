import type { ReactNode } from "react";
import {
  Plus,
  Trash2,
  MapPin,
  CalendarCheck,
  CalendarRange,
  Clock,
  Timer,
  Check,
  Gem,
  Lock,
  Hourglass,
  ChevronUp,
  ChevronDown,
  Minus,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { DIAS, type FranjaExcluida } from "@/lib/types";
import { useCareer } from "@/lib/career";

function LockedSection({
  locked,
  onUpgrade,
  children,
}: {
  locked: boolean;
  onUpgrade?: () => void;
  children: ReactNode;
}) {
  if (!locked) return <>{children}</>;
  return (
    <div className="relative">
      <div className="pointer-events-none select-none opacity-50">
        {children}
      </div>
      {onUpgrade && (
        <button
          type="button"
          onClick={onUpgrade}
          aria-label="Hacete Pro para usar este filtro"
          className="absolute inset-0 cursor-pointer rounded-lg"
        />
      )}
    </div>
  );
}

// Grilla de horas de las franjas. El rango coincide con el del calendario y con
// el de la oferta real (ningún curso arranca antes de las 7 ni termina después
// de las 23), y el paso de 15' con la única granularidad que publica la fuente
// (los cursos caen siempre en :00, :15, :30 o :45).
const HORA_MIN = 7;
const HORA_MAX = 23;
const PASO_MINUTOS = 15;

const HORAS: string[] = [];
for (let m = HORA_MIN * 60; m <= HORA_MAX * 60; m += PASO_MINUTOS) {
  const hh = String(Math.floor(m / 60)).padStart(2, "0");
  const mm = String(m % 60).padStart(2, "0");
  HORAS.push(`${hh}:${mm}`);
}

// Las horas son "HH:MM" con cero a la izquierda, así que comparar y ordenar
// como strings alcanza: no hace falta parsear a minutos.
function horaSiguiente(hora: string): string {
  return HORAS.find((h) => h > hora) ?? HORAS[HORAS.length - 1];
}

// Selector propio en vez de <input type="time">: el picker nativo de hora tira
// abajo el webview de los navegadores embebidos de Instagram y TikTok, por
// donde entra buena parte del tráfico, y el usuario pierde todo lo que había
// cargado. Esto es DOM puro, así que se comporta igual en cualquier navegador.
function TimeSelect({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
  ariaLabel: string;
}) {
  // Un valor fuera de la grilla (favorito viejo o ?q= armado a mano) tiene que
  // seguir viéndose: sin item que lo matchee, Radix deja el trigger vacío.
  const items = options.includes(value)
    ? options
    : [value, ...options].sort();
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={ariaLabel} className="h-9 w-full max-w-[8rem]">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {items.map((h) => (
          <SelectItem key={h} value={h}>
            {h}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function NumberStepper({
  value,
  onChange,
  step,
  min = 0,
  max,
  placeholder,
  ariaLabel,
}: {
  value: number | null;
  onChange: (v: number | null) => void;
  step: number;
  min?: number;
  max?: number;
  placeholder?: string;
  ariaLabel?: string;
}) {
  const clamp = (n: number) => {
    let r = Math.max(min, n);
    if (max != null) r = Math.min(max, r);
    return r;
  };
  const inc = () => onChange(value == null ? min : clamp(value + step));
  const dec = () => onChange(value == null ? min : clamp(value - step));
  const decDisabled = value != null && value <= min;
  return (
    <div className="flex h-11 w-full items-stretch overflow-hidden rounded-lg border border-input bg-white sm:h-9">
      {/* Botón menos: solo mobile, a la izquierda del input */}
      <button
        type="button"
        aria-label="Disminuir"
        onClick={dec}
        disabled={decDisabled}
        className="flex w-12 shrink-0 items-center justify-center border-r border-input text-muted-foreground transition-colors hover:bg-accent hover:text-foreground active:bg-accent disabled:cursor-not-allowed disabled:opacity-40 sm:hidden"
      >
        <Minus className="size-4" strokeWidth={2.5} />
      </button>
      <Input
        type="number"
        min={min}
        max={max}
        step={step}
        inputMode="decimal"
        placeholder={placeholder}
        aria-label={ariaLabel}
        value={value ?? ""}
        onChange={(e) => {
          const v = e.target.value;
          if (v === "") {
            onChange(null);
            return;
          }
          const n = Number(v);
          if (Number.isFinite(n)) onChange(clamp(n));
        }}
        className="h-full min-h-0 flex-1 rounded-none border-0 bg-transparent px-2 text-center shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none [appearance:textfield] sm:text-left"
      />
      {/* Botón más: solo mobile, a la derecha del input */}
      <button
        type="button"
        aria-label="Aumentar"
        onClick={inc}
        className="flex w-12 shrink-0 items-center justify-center border-l border-input text-muted-foreground transition-colors hover:bg-accent hover:text-foreground active:bg-accent sm:hidden"
      >
        <Plus className="size-4" strokeWidth={2.5} />
      </button>
      {/* Chevrons apilados: solo desktop, a la derecha del input */}
      <div className="hidden flex-col border-l border-input sm:flex">
        <button
          type="button"
          aria-label="Aumentar"
          onClick={inc}
          className="flex flex-1 items-center justify-center px-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <ChevronUp className="size-3" strokeWidth={2.5} />
        </button>
        <button
          type="button"
          aria-label="Disminuir"
          onClick={dec}
          disabled={decDisabled}
          className="flex flex-1 items-center justify-center border-t border-input px-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
        >
          <ChevronDown className="size-3" strokeWidth={2.5} />
        </button>
      </div>
    </div>
  );
}

const DIA_LABELS_SHORT: Record<string, string> = {
  lunes: "Lun",
  martes: "Mar",
  miercoles: "Mié",
  jueves: "Jue",
  viernes: "Vie",
  sabado: "Sáb",
};

interface Props {
  diasPermitidos: string[];
  onDiasPermitidosChange: (dias: string[]) => void;

  franjas: FranjaExcluida[];
  onFranjasChange: (franjas: FranjaExcluida[]) => void;

  sedesPermitidas: string[];
  onSedesChange: (sedes: string[]) => void;

  maxBacheHoras: number | null;
  onMaxBacheHorasChange: (h: number | null) => void;

  minDiasSemana: number | null;
  onMinDiasSemanaChange: (v: number | null) => void;
  maxDiasSemana: number | null;
  onMaxDiasSemanaChange: (v: number | null) => void;

  minHorasDia: number | null;
  onMinHorasDiaChange: (v: number | null) => void;
  maxHorasDia: number | null;
  onMaxHorasDiaChange: (v: number | null) => void;

  soloCupos: boolean;
  onSoloCuposChange: (v: boolean) => void;

  isPaid: boolean;
  isLoading?: boolean;
  onUpgrade?: () => void;
}

export function RestriccionesPanel({
  diasPermitidos,
  onDiasPermitidosChange,
  franjas,
  onFranjasChange,
  sedesPermitidas,
  onSedesChange,
  maxBacheHoras,
  onMaxBacheHorasChange,
  minDiasSemana,
  onMinDiasSemanaChange,
  maxDiasSemana,
  onMaxDiasSemanaChange,
  minHorasDia,
  onMinHorasDiaChange,
  maxHorasDia,
  onMaxHorasDiaChange,
  soloCupos,
  onSoloCuposChange,
  isPaid,
  isLoading,
  onUpgrade,
}: Props) {
  const { sedesDisponibles } = useCareer();
  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-16 w-full rounded-lg" />
        <div className="space-y-3">
          <Skeleton className="h-4 w-44" />
          <div className="flex flex-wrap gap-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-20 rounded-full" />
            ))}
          </div>
        </div>
        <Skeleton className="h-px w-full" />
        <div className="space-y-3">
          <Skeleton className="h-4 w-52" />
          <Skeleton className="h-12 w-full rounded-lg" />
        </div>
        <Skeleton className="h-px w-full" />
        <div className="space-y-3">
          <Skeleton className="h-4 w-40" />
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full rounded-lg" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  function toggleDia(dia: string) {
    onDiasPermitidosChange(
      diasPermitidos.includes(dia)
        ? diasPermitidos.filter((d) => d !== dia)
        : [...diasPermitidos, dia],
    );
  }

  function toggleSede(codigo: string) {
    onSedesChange(
      sedesPermitidas.includes(codigo)
        ? sedesPermitidas.filter((s) => s !== codigo)
        : [...sedesPermitidas, codigo],
    );
  }

  function addFranja() {
    onFranjasChange([
      ...franjas,
      { dias: ["lunes"], hora_inicio: "09:00", hora_fin: "12:00" },
    ]);
  }

  function updateFranja(idx: number, patch: Partial<FranjaExcluida>) {
    onFranjasChange(
      franjas.map((f, i) => (i === idx ? { ...f, ...patch } : f)),
    );
  }

  // Mantener inicio < fin: mover el fin si el nuevo inicio lo alcanza.
  function setFranjaInicio(idx: number, hora: string) {
    const f = franjas[idx];
    updateFranja(
      idx,
      hora >= f.hora_fin
        ? { hora_inicio: hora, hora_fin: horaSiguiente(hora) }
        : { hora_inicio: hora },
    );
  }

  function toggleFranjaDia(idx: number, dia: string) {
    const f = franjas[idx];
    const nuevo = f.dias.includes(dia)
      ? f.dias.filter((d) => d !== dia)
      : [...f.dias, dia];
    if (nuevo.length === 0) return; // no permitir franja sin días
    updateFranja(idx, { dias: nuevo });
  }

  function removeFranja(idx: number) {
    onFranjasChange(franjas.filter((_, i) => i !== idx));
  }

  // Mantener min <= max: mover el otro extremo si el nuevo valor lo cruza.
  function setMinDias(v: number | null) {
    onMinDiasSemanaChange(v);
    if (v != null && maxDiasSemana != null && v > maxDiasSemana) {
      onMaxDiasSemanaChange(v);
    }
  }
  function setMaxDias(v: number | null) {
    onMaxDiasSemanaChange(v);
    if (v != null && minDiasSemana != null && v < minDiasSemana) {
      onMinDiasSemanaChange(v);
    }
  }
  function setMinHoras(v: number | null) {
    onMinHorasDiaChange(v);
    if (v != null && maxHorasDia != null && v > maxHorasDia) {
      onMaxHorasDiaChange(v);
    }
  }
  function setMaxHoras(v: number | null) {
    onMaxHorasDiaChange(v);
    if (v != null && minHorasDia != null && v < minHorasDia) {
      onMinHorasDiaChange(v);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="space-y-6">
          {/* Días permitidos */}
          <section className="space-y-3">
            <div className="flex items-center gap-2">
              <CalendarCheck className="size-4 text-muted-foreground" />
              <Label className="text-sm">Días que querés cursar</Label>
            </div>
            <div className="flex flex-wrap gap-2">
              {DIAS.map((dia) => {
                const active = diasPermitidos.includes(dia);
                return (
                  <button
                    key={dia}
                    type="button"
                    onClick={() => toggleDia(dia)}
                    className={
                      "inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors max-sm:min-h-[44px] " +
                      (active
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-white text-muted-foreground hover:bg-accent")
                    }
                  >
                    {active && <Check className="size-3.5" strokeWidth={3} />}
                    {DIA_LABELS_SHORT[dia]}
                  </button>
                );
              })}
            </div>
            {diasPermitidos.length === 0 && (
              <p className="text-xs text-muted-foreground">
                Si no marcás ninguno, no se podrán generar planes.
              </p>
            )}
          </section>

          <Separator />

          {/* Solo materias con cupos */}
          <section className="space-y-3">
            <div className="flex items-center gap-2">
              <Users className="size-4 text-muted-foreground" />
              <Label className="text-sm">Solo materias con cupos</Label>
            </div>
            <p className="text-xs text-muted-foreground">
              Descarta opciones cuya comisión no tenga cupos disponibles.
            </p>
            <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-border bg-white px-3 py-2.5 transition-colors hover:bg-accent max-sm:min-h-[44px]">
              <Switch checked={soloCupos} onCheckedChange={onSoloCuposChange} />
              <span className="flex-1 text-sm">Mostrar solo con cupos</span>
            </label>
          </section>

          <Separator />

          {!isPaid && (
            <div className="flex flex-col gap-3 rounded-lg border border-[#EC990B]/40 bg-[#EC990B]/10 px-4 py-3 sm:flex-row sm:items-start">
              <div className="flex flex-1 items-start gap-3">
                <Lock className="mt-0.5 size-4 shrink-0 text-[#EC990B]" />
                <div className="flex-1 text-sm">
                  <p className="font-medium text-foreground">
                    Algunos filtros requieren Pro
                  </p>
                  <p className="mt-0.5 text-muted-foreground">
                    Hacete Pro para usar franjas horarias, sedes, bache máximo y
                    límites de días y horas de cursada.
                  </p>
                </div>
              </div>
              {onUpgrade && (
                <Button
                  size="sm"
                  onClick={onUpgrade}
                  className="w-full shrink-0 bg-[#EC990B] text-white hover:bg-[#EC990B]/90 sm:w-auto"
                >
                  <Gem className="size-4" />
                  Hacete Pro
                </Button>
              )}
            </div>
          )}

          {/* Franjas horarias bloqueadas (multi-día) */}
          <LockedSection locked={!isPaid} onUpgrade={onUpgrade}>
            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Clock className="size-4 text-muted-foreground" />
                  <Label className="text-sm">Franjas horarias bloqueadas</Label>
                </div>
                <Button variant="outline" size="sm" onClick={addFranja}>
                  <Plus className="size-3.5" />
                  Agregar
                </Button>
              </div>
              {franjas.length === 0 ? (
                <p className="rounded-lg bg-muted/50 px-4 py-3 text-sm text-muted-foreground">
                  Podes bloquear franjas horarias en las que no queres cursar
                  materias
                </p>
              ) : (
                <div className="space-y-2">
                  {franjas.map((f, i) => (
                    <div
                      key={i}
                      className="space-y-2 rounded-lg border border-border bg-background p-3"
                    >
                      <div className="flex flex-wrap items-center gap-1.5">
                        {DIAS.map((d) => {
                          const active = f.dias.includes(d);
                          return (
                            <button
                              key={d}
                              type="button"
                              onClick={() => toggleFranjaDia(i, d)}
                              className={
                                "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-medium transition-colors max-sm:min-h-[44px] " +
                                (active
                                  ? "border-primary bg-primary text-primary-foreground"
                                  : "border-border bg-white text-muted-foreground hover:bg-accent")
                              }
                            >
                              {active && (
                                <Check className="size-3" strokeWidth={3} />
                              )}
                              {DIA_LABELS_SHORT[d]}
                            </button>
                          );
                        })}
                      </div>
                      <div className="flex items-center gap-2">
                        <TimeSelect
                          value={f.hora_inicio}
                          onChange={(h) => setFranjaInicio(i, h)}
                          options={HORAS.slice(0, -1)}
                          ariaLabel="Hora de inicio de la franja"
                        />
                        <span className="text-sm text-muted-foreground">a</span>
                        <TimeSelect
                          value={f.hora_fin}
                          onChange={(h) => updateFranja(i, { hora_fin: h })}
                          options={HORAS.filter((h) => h > f.hora_inicio)}
                          ariaLabel="Hora de fin de la franja"
                        />
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => removeFranja(i)}
                          className="ml-auto text-muted-foreground hover:text-destructive"
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </LockedSection>

          <Separator />

          {/* Sedes */}
          {sedesDisponibles.length > 1 && (
            <>
              <LockedSection locked={!isPaid} onUpgrade={onUpgrade}>
                <section className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <MapPin className="size-4 text-muted-foreground" />
                      <Label className="text-sm">Sedes permitidas</Label>
                    </div>
                    {sedesPermitidas.length > 0 && (
                      <button
                        type="button"
                        onClick={() => onSedesChange([])}
                        className="text-xs font-medium text-primary hover:underline"
                      >
                        Limpiar
                      </button>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Si no seleccionás ninguna, se permiten todas.
                  </p>
                  <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                    {sedesDisponibles.map((s) => (
                      <label
                        key={s.codigo}
                        className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-border bg-white px-3 py-2 transition-colors hover:bg-accent"
                      >
                        <Checkbox
                          checked={sedesPermitidas.includes(s.codigo)}
                          onCheckedChange={() => toggleSede(s.codigo)}
                        />
                        <span className="flex-1 text-sm">{s.nombre}</span>
                        <span className="text-xs text-muted-foreground">
                          {s.codigo}
                        </span>
                      </label>
                    ))}
                  </div>
                </section>
              </LockedSection>

              <Separator />
            </>
          )}

          {/* Bache máximo */}
          <LockedSection locked={!isPaid} onUpgrade={onUpgrade}>
            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Hourglass className="size-4 text-muted-foreground" />
                  <Label className="text-sm">Bache máximo entre clases</Label>
                </div>
                {maxBacheHoras !== null && (
                  <button
                    type="button"
                    onClick={() => onMaxBacheHorasChange(null)}
                    className="text-xs font-medium text-primary hover:underline"
                  >
                    Limpiar
                  </button>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Descartar planes con un hueco mayor a este valor entre clases
                consecutivas del mismo día.
              </p>
              <div className="flex items-center gap-2">
                <div className="flex-1 sm:w-28 sm:flex-none">
                  <NumberStepper
                    value={maxBacheHoras}
                    onChange={onMaxBacheHorasChange}
                    step={0.5}
                    min={0}
                    placeholder="Sin límite"
                    ariaLabel="Bache máximo en horas"
                  />
                </div>
                <span className="text-sm text-muted-foreground">horas</span>
              </div>
            </section>
          </LockedSection>

          <Separator />

          {/* Días de cursada por semana (min/max) */}
          <LockedSection locked={!isPaid} onUpgrade={onUpgrade}>
            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <CalendarRange className="size-4 text-muted-foreground" />
                  <Label className="text-sm">Días de cursada por semana</Label>
                </div>
                {(minDiasSemana !== null || maxDiasSemana !== null) && (
                  <button
                    type="button"
                    onClick={() => {
                      onMinDiasSemanaChange(null);
                      onMaxDiasSemanaChange(null);
                    }}
                    className="text-xs font-medium text-primary hover:underline"
                  >
                    Limpiar
                  </button>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Cuántos días de la semana queres cursar.
              </p>
              <div className="grid grid-cols-2 gap-3 sm:flex sm:items-end sm:gap-4">
                <div className="space-y-1.5 sm:w-24">
                  <Label className="text-xs text-muted-foreground">
                    Mínimo
                  </Label>
                  <NumberStepper
                    value={minDiasSemana}
                    onChange={setMinDias}
                    step={1}
                    min={1}
                    max={7}
                    placeholder="—"
                    ariaLabel="Mínimo de días por semana"
                  />
                </div>
                <div className="space-y-1.5 sm:w-24">
                  <Label className="text-xs text-muted-foreground">
                    Máximo
                  </Label>
                  <NumberStepper
                    value={maxDiasSemana}
                    onChange={setMaxDias}
                    step={1}
                    min={1}
                    max={7}
                    placeholder="—"
                    ariaLabel="Máximo de días por semana"
                  />
                </div>
              </div>
            </section>
          </LockedSection>

          <Separator />

          {/* Horas de cursada por día (min/max) */}
          <LockedSection locked={!isPaid} onUpgrade={onUpgrade}>
            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Timer className="size-4 text-muted-foreground" />
                  <Label className="text-sm">Horas de cursada por día</Label>
                </div>
                {(minHorasDia !== null || maxHorasDia !== null) && (
                  <button
                    type="button"
                    onClick={() => {
                      onMinHorasDiaChange(null);
                      onMaxHorasDiaChange(null);
                    }}
                    className="text-xs font-medium text-primary hover:underline"
                  >
                    Limpiar
                  </button>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Horas por día en la facultad, de tu primera a tu última clase
                (los baches cuentan).
              </p>
              <div className="grid grid-cols-2 gap-3 sm:flex sm:items-end sm:gap-4">
                <div className="space-y-1.5 sm:w-24">
                  <Label className="text-xs text-muted-foreground">
                    Mínimo
                  </Label>
                  <NumberStepper
                    value={minHorasDia}
                    onChange={setMinHoras}
                    step={0.5}
                    min={0}
                    placeholder="—"
                    ariaLabel="Mínimo de horas por día"
                  />
                </div>
                <div className="space-y-1.5 sm:w-24">
                  <Label className="text-xs text-muted-foreground">
                    Máximo
                  </Label>
                  <NumberStepper
                    value={maxHorasDia}
                    onChange={setMaxHoras}
                    step={0.5}
                    min={0}
                    placeholder="—"
                    ariaLabel="Máximo de horas por día"
                  />
                </div>
              </div>
            </section>
          </LockedSection>
        </div>
      </div>
    </div>
  );
}
