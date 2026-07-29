import { useMemo, useRef, useState } from "react";
import type { Plan, CursoEnPlan, FranjaExcluida } from "@/lib/types";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer";
import {
  AlertTriangle,
  Clock,
  DoorOpen,
  GraduationCap,
  Lock,
  MapPin,
  User,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useIsTouchDevice } from "@/lib/useIsTouchDevice";

const DIAS_DISPLAY = [
  { key: "lunes", short: "Lun" },
  { key: "martes", short: "Mar" },
  { key: "miercoles", short: "Mié" },
  { key: "jueves", short: "Jue" },
  { key: "viernes", short: "Vie" },
  { key: "sabado", short: "Sáb" },
];

const PIXELS_PER_HOUR_NORMAL = 32;
const PIXELS_PER_HOUR_COMPACTO = 16;

interface CursoConContexto extends CursoEnPlan {
  materia_codigo: number;
  materia_nombre: string;
  materia_color: string;
  catedra_titular: string | null;
  sinCupos: boolean;
  // Vacantes de la comisión de la opción (autoritativas para toda la opción).
  cuposRestantes: number | null;
}

interface Props {
  plan: Plan | null;
  compacto?: boolean;
  showLeyenda?: boolean;
  // Las vacantes viajan dentro del plan, así que en un plan guardado son las
  // del momento en que se guardó. Apagarlo evita mostrar cupos vencidos.
  showCupos?: boolean;
  // Franjas con las que se generó el plan, para pintarlas como bloqueadas.
  franjasBloqueadas?: FranjaExcluida[];
}

export function PlanLeyenda({
  plan,
  showCatedra = true,
  size = "normal",
}: {
  plan: Plan;
  showCatedra?: boolean;
  size?: "normal" | "compacto";
}) {
  const compacto = size === "compacto";
  return (
    <div
      className={cn(
        "flex flex-wrap",
        compacto ? "gap-1.5" : "gap-2 wide:gap-3",
      )}
    >
      {plan.opciones.map((op, idx) => {
        const palette = PALETTE[idx % PALETTE.length];
        return (
          <div
            key={op.materia_codigo}
            className={cn(
              "flex items-start gap-2 rounded-lg border border-border bg-background",
              compacto ? "px-2 py-1 text-[11px]" : "px-3 py-1.5 text-xs",
            )}
          >
            <div className="flex flex-col items-center justify-center h-full">
              <span
                className={cn(
                  "shrink-0 rounded-full",
                  compacto ? "size-2" : "size-3",
                  palette.bg,
                )}
              />
            </div>

            <div className="flex flex-col">
              <span
                className={cn(
                  "font-medium",
                  compacto ? "line-clamp-1" : "line-clamp-2",
                )}
              >
                {op.materia_nombre}
              </span>
              {showCatedra && (
                <span className="text-muted-foreground">
                  cát {op.catedra_id}
                  {op.catedra_titular ? ` (${op.catedra_titular})` : ""}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Paleta acorde al primario (variaciones de hue cercanas + neutros).
const PALETTE = [
  { bg: "bg-primary text-primary-foreground", dot: "bg-primary-foreground/80" },
  { bg: "bg-rose-500 text-white", dot: "bg-white/80" },
  { bg: "bg-amber-500 text-white", dot: "bg-white/80" },
  { bg: "bg-emerald-600 text-white", dot: "bg-white/80" },
  { bg: "bg-sky-600 text-white", dot: "bg-white/80" },
  { bg: "bg-violet-600 text-white", dot: "bg-white/80" },
  { bg: "bg-fuchsia-600 text-white", dot: "bg-white/80" },
  { bg: "bg-teal-600 text-white", dot: "bg-white/80" },
];

function parseTime(t: string | null): number | null {
  if (!t) return null;
  const [h, m] = t.split(":").map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  return h + m / 60;
}

function formatTipo(tipo: string, codigo: string): string {
  const map: Record<string, string> = {
    teorico: "Teó",
    seminario: "Sem",
    comision: "Com",
  };
  return `${map[tipo] ?? tipo} ${codigo}`;
}

function formatHM(t: string | null): string {
  if (!t) return "";
  return t.slice(0, 5);
}

interface Bloqueo {
  inicio: number;
  fin: number;
}

// Franjas → intervalos por día, recortados a la grilla y fusionados: dos
// franjas que se pisan tienen que verse como un solo bloque (si no, el rayado
// se superpone y el rótulo "Bloqueado" aparece repetido).
function bloqueosPorDia(
  franjas: FranjaExcluida[],
  horaMin: number,
  horaMax: number,
): Map<string, Bloqueo[]> {
  const porDia = new Map<string, Bloqueo[]>();
  franjas.forEach((f) => {
    const inicio = parseTime(f.hora_inicio);
    const fin = parseTime(f.hora_fin);
    if (inicio === null || fin === null) return;
    const from = Math.max(inicio, horaMin);
    const to = Math.min(fin, horaMax);
    if (to <= from) return;
    f.dias.forEach((dia) => {
      const acc = porDia.get(dia);
      if (acc) acc.push({ inicio: from, fin: to });
      else porDia.set(dia, [{ inicio: from, fin: to }]);
    });
  });

  porDia.forEach((intervalos, dia) => {
    const ordenados = [...intervalos].sort((a, b) => a.inicio - b.inicio);
    const merged: Bloqueo[] = [];
    ordenados.forEach((iv) => {
      const last = merged[merged.length - 1];
      if (last && iv.inicio <= last.fin) last.fin = Math.max(last.fin, iv.fin);
      else merged.push({ ...iv });
    });
    porDia.set(dia, merged);
  });

  return porDia;
}

function hhmm(hora: number): string {
  const h = Math.floor(hora);
  const m = Math.round((hora - h) * 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function FranjaBloqueadaBloque({
  bloqueo,
  compacto,
  top,
  height,
}: {
  bloqueo: Bloqueo;
  compacto: boolean;
  top: number;
  height: number;
}) {
  const rango = `${hhmm(bloqueo.inicio)}–${hhmm(bloqueo.fin)}`;
  const showLabel = height >= 22;
  const stacked = height >= 52;
  const showRango = height >= 62;

  return (
    <div
      title={`Bloqueado ${rango}`}
      className={cn(
        "absolute inset-x-0 z-0 flex items-center justify-center overflow-hidden",
        "border-y border-muted-foreground/20 bg-muted-foreground/[0.07] text-foreground/75",
        compacto ? "text-[9px]" : "text-[10px]",
      )}
      style={{
        top,
        height,
        backgroundImage:
          "repeating-linear-gradient(45deg, transparent 0 5px, hsl(var(--muted-foreground) / 0.16) 5px 7px)",
      }}
    >
      <span className="sr-only">Bloqueado de {rango.replace("–", " a ")}</span>
      <div
        className={cn(
          "flex min-w-0 items-center justify-center gap-1 px-1",
          stacked && "flex-col gap-0.5",
        )}
      >
        <Lock
          aria-hidden
          className={cn("shrink-0", compacto ? "size-2.5" : "size-3")}
          strokeWidth={2.5}
        />
        {showLabel && (
          <span className="truncate font-semibold leading-none">Bloqueado</span>
        )}
        {showRango && <span className="truncate leading-none">{rango}</span>}
      </div>
    </div>
  );
}

interface CursoBloqueProps {
  curso: CursoConContexto;
  compacto: boolean;
  top: number;
  height: number;
}

// Semáforo de cupos: rojo ≤10, amarillo ≤30, verde >30.
function cuposColor(cupos: number): string {
  if (cupos <= 10) return "text-red-600";
  if (cupos <= 30) return "text-amber-600";
  return "text-green-600";
}

function CursoDetalle({
  curso,
  size = "popover",
}: {
  curso: CursoConContexto;
  size?: "popover" | "drawer";
}) {
  const iconSize = size === "drawer" ? "size-4" : "size-3.5";
  const textCls =
    size === "drawer"
      ? "flex items-center gap-2 text-sm text-muted-foreground"
      : "flex items-center gap-1.5 text-muted-foreground";
  return (
    <div className={size === "drawer" ? "space-y-2.5" : "space-y-1.5"}>
      {size === "popover" && (
        <div className="text-sm font-semibold">{curso.materia_nombre}</div>
      )}
      {curso.sinCupos && (
        <div className="flex items-center gap-1.5 rounded-md bg-amber-50 px-2 py-1 text-amber-900">
          <AlertTriangle className={cn("shrink-0", iconSize)} />
          <span className="font-medium">Sin cupos disponibles</span>
        </div>
      )}
      <div className={textCls}>
        <Clock className={cn("shrink-0", iconSize)} />
        <span>
          {formatTipo(curso.tipo, curso.codigo)} · {formatHM(curso.hora_inicio)}
          –{formatHM(curso.hora_fin)}
        </span>
      </div>
      {curso.aula && (
        <div className={textCls}>
          <DoorOpen className={cn("shrink-0", iconSize)} />
          <span>Aula {curso.aula}</span>
        </div>
      )}
      {curso.profesor && (
        <div className={textCls}>
          <User className={cn("shrink-0", iconSize)} />
          <span>{curso.profesor}</span>
        </div>
      )}
      {curso.sede && (
        <div className={textCls}>
          <MapPin className={cn("shrink-0", iconSize)} />
          <span>{curso.sede}</span>
        </div>
      )}
      {curso.catedra_titular && (
        <div className={textCls}>
          <GraduationCap className={cn("shrink-0", iconSize)} />
          <span>Cátedra: {curso.catedra_titular}</span>
        </div>
      )}
      {curso.cuposRestantes != null && curso.cuposRestantes > 0 && (
        <div className={cn(textCls, cuposColor(curso.cuposRestantes))}>
          <Users className={cn("shrink-0", iconSize)} />
          <span>
            {curso.cuposRestantes}{" "}
            {curso.cuposRestantes === 1
              ? "cupo disponible"
              : "cupos disponibles"}
          </span>
        </div>
      )}
    </div>
  );
}

function CursoBloque({ curso, compacto, top, height }: CursoBloqueProps) {
  const [open, setOpen] = useState(false);
  const timer = useRef<number | null>(null);
  const isTouch = useIsTouchDevice();

  const cancel = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };
  const onEnter = () => {
    cancel();
    setOpen(true);
  };
  const onLeave = () => {
    cancel();
    timer.current = window.setTimeout(() => setOpen(false), 120);
  };

  const bloque = (
    <div
      className={cn(
        "absolute left-1 right-1 z-10 cursor-pointer overflow-hidden rounded-md shadow-sm",
        compacto
          ? "flex items-center px-1.5 py-0 text-[10px]"
          : "px-2 py-1.5 text-[11px]",
        curso.materia_color,
      )}
      style={{ top, height }}
      onMouseEnter={isTouch ? undefined : onEnter}
      onMouseLeave={isTouch ? undefined : onLeave}
    >
      {curso.sinCupos && (
        <AlertTriangle
          aria-label="Sin cupos disponibles"
          className={cn(
            "absolute right-1 top-1 fill-amber-400 text-amber-900 drop-shadow",
            compacto ? "size-3" : "size-3.5",
          )}
          strokeWidth={2.5}
        />
      )}
      {compacto ? (
        <div className="line-clamp-1 font-medium leading-tight">
          {curso.materia_nombre}
        </div>
      ) : (
        <>
          <div className="line-clamp-1 font-semibold leading-tight">
            {curso.materia_nombre}
          </div>
          <div className="opacity-90 leading-tight">
            {formatTipo(curso.tipo, curso.codigo)} ·{" "}
            {formatHM(curso.hora_inicio)}–{formatHM(curso.hora_fin)}
          </div>
          {curso.aula && (
            <div className="opacity-80 leading-tight">{curso.aula}</div>
          )}
        </>
      )}
    </div>
  );

  if (isTouch) {
    return (
      <Drawer>
        <DrawerTrigger asChild>{bloque}</DrawerTrigger>
        <DrawerContent>
          <DrawerHeader>
            <DrawerTitle>{curso.materia_nombre}</DrawerTitle>
          </DrawerHeader>
          <div className="px-4 pb-6">
            <CursoDetalle curso={curso} size="drawer" />
          </div>
        </DrawerContent>
      </Drawer>
    );
  }

  return (
    <Popover open={open} onOpenChange={undefined}>
      <PopoverTrigger asChild>{bloque}</PopoverTrigger>
      <PopoverContent
        className="w-auto min-w-[200px] max-w-[280px] p-3 text-xs"
        side="right"
        align="start"
        sideOffset={6}
        onMouseEnter={onEnter}
        onMouseLeave={onLeave}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <CursoDetalle curso={curso} size="popover" />
      </PopoverContent>
    </Popover>
  );
}

export function CalendarioPlan({
  plan,
  compacto = false,
  showLeyenda = true,
  showCupos = true,
  franjasBloqueadas,
}: Props) {
  const horaMin = 7;
  const horaMax = 23;
  const PIXELS_PER_HOUR = compacto
    ? PIXELS_PER_HOUR_COMPACTO
    : PIXELS_PER_HOUR_NORMAL;
  const cursos = useMemo<CursoConContexto[]>(() => {
    if (!plan) return [];
    const cs: CursoConContexto[] = [];
    plan.opciones.forEach((op, idx) => {
      const palette = PALETTE[idx % PALETTE.length];
      // Solo la comisión tiene `vacantes` cargado: teóricos/seminarios
      // comparten el cupo de la comisión via comision_obliga.
      const comision = op.cursos.find((c) => c.tipo === "comision");
      // Se corta acá y no en cada render: con ambos en neutro se apagan solos
      // el contador, el cartel de "sin cupos" y el ícono sobre el bloque.
      const cuposRestantes = showCupos ? (comision?.vacantes ?? null) : null;
      const sinCupos =
        showCupos &&
        comision != null &&
        (comision.vacantes == null || comision.vacantes <= 0);
      op.cursos.forEach((c) => {
        cs.push({
          ...c,
          materia_codigo: op.materia_codigo,
          materia_nombre: op.materia_nombre,
          materia_color: palette.bg,
          catedra_titular: op.catedra_titular,
          sinCupos,
          cuposRestantes,
        });
      });
    });
    return cs;
  }, [plan, showCupos]);

  const bloqueos = useMemo(
    () => bloqueosPorDia(franjasBloqueadas ?? [], horaMin, horaMax),
    [franjasBloqueadas],
  );

  if (!plan) {
    return (
      <div className="flex min-h-[480px] items-center justify-center rounded-2xl border border-dashed border-border bg-muted/30 p-12 text-center">
        <div className="max-w-md space-y-2">
          <p className="text-sm font-medium">Sin plan generado todavía</p>
          <p className="text-xs text-muted-foreground">
            Seleccioná al menos una materia y ajustá las restricciones, después
            apretá "Generar planes" para ver las combinaciones posibles acá.
          </p>
        </div>
      </div>
    );
  }

  const horas = Array.from(
    { length: horaMax - horaMin },
    (_, i) => horaMin + i,
  );

  // Agrupar por día
  const cursosPorDia = new Map<string, CursoConContexto[]>();
  DIAS_DISPLAY.forEach((d) => cursosPorDia.set(d.key, []));
  cursos.forEach((c) => {
    if (c.dia && cursosPorDia.has(c.dia)) {
      cursosPorDia.get(c.dia)!.push(c);
    }
  });

  const minBloque = compacto ? 14 : 28;
  const gridCols = compacto
    ? "grid-cols-[72px_repeat(6,1fr)]"
    : "grid-cols-[40px_repeat(6,1fr)] wide:grid-cols-[64px_repeat(6,1fr)]";

  return (
    <div>
      <div className="-mx-6 overflow-x-auto overflow-y-clip px-6 wide:mx-0 wide:px-0">
        <div className="min-w-[560px] rounded-2xl border border-border bg-card wide:min-w-[760px]">
          <div className={cn("grid border-b border-border", gridCols)}>
            <div className="p-3 text-xs font-medium text-muted-foreground" />
            {DIAS_DISPLAY.map((d) => (
              <div
                key={d.key}
                className="p-3 text-center text-xs font-semibold uppercase tracking-wide text-muted-foreground"
              >
                {d.short}
              </div>
            ))}
          </div>

          <div className={cn("grid", gridCols)}>
            {/* Columna de horas */}
            <div
              className="relative border-r border-border"
              style={{ height: PIXELS_PER_HOUR * horas.length }}
            >
              {compacto
                ? horas.map((h, i) => (
                    <div
                      key={h}
                      className="absolute inset-x-0 flex items-center justify-end pr-1.5 text-[9px] font-medium leading-none text-muted-foreground"
                      style={{
                        top: i * PIXELS_PER_HOUR,
                        height: PIXELS_PER_HOUR,
                      }}
                    >
                      {String(h).padStart(2, "0")}:00 -{" "}
                      {String(h + 1).padStart(2, "0")}:00
                    </div>
                  ))
                : Array.from(
                    { length: horaMax - horaMin + 1 },
                    (_, i) => horaMin + i,
                  ).map((h, i) => (
                    <div
                      key={h}
                      className="absolute right-0 flex -translate-y-1/2 justify-end pr-1 text-[10px] font-medium text-muted-foreground wide:pr-2"
                      style={{ top: i * PIXELS_PER_HOUR }}
                    >
                      {String(h).padStart(2, "0")}:00
                    </div>
                  ))}
            </div>

            {DIAS_DISPLAY.map((d) => {
              const cs = cursosPorDia.get(d.key)!;
              return (
                <div
                  key={d.key}
                  className="relative border-r border-border last:border-r-0"
                  style={{ height: PIXELS_PER_HOUR * horas.length }}
                >
                  {/* Líneas de hora */}
                  {horas.map((h, i) => (
                    <div
                      key={h}
                      className="absolute inset-x-0 border-b border-border/50"
                      style={{ top: i * PIXELS_PER_HOUR }}
                    />
                  ))}
                  {/* Franjas bloqueadas por el filtro */}
                  {(bloqueos.get(d.key) ?? []).map((b) => (
                    <FranjaBloqueadaBloque
                      key={`${b.inicio}-${b.fin}`}
                      bloqueo={b}
                      compacto={compacto}
                      top={(b.inicio - horaMin) * PIXELS_PER_HOUR}
                      height={(b.fin - b.inicio) * PIXELS_PER_HOUR}
                    />
                  ))}
                  {/* Bloques de cursos */}
                  {cs.map((c) => {
                    const start = parseTime(c.hora_inicio);
                    const end = parseTime(c.hora_fin);
                    if (start === null || end === null) return null;
                    const top = (start - horaMin) * PIXELS_PER_HOUR;
                    const height = Math.max(
                      minBloque,
                      (end - start) * PIXELS_PER_HOUR,
                    );
                    return (
                      <CursoBloque
                        key={c.id}
                        curso={c}
                        compacto={compacto}
                        top={top}
                        height={height}
                      />
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Leyenda */}
      {showLeyenda && (
        <div className="mt-4">
          <PlanLeyenda plan={plan} />
        </div>
      )}
    </div>
  );
}
