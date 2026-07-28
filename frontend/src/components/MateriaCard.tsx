import { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  X,
  Loader2,
  Users,
  GraduationCap,
  Gem,
  Hash,
  MapPin,
  Star,
} from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { StarRating } from "@/components/StarRating";
import { api } from "@/lib/api";
import { useSubscription } from "@/lib/useSubscription";
import { useIsWide } from "@/lib/useIsWide";
import { useClampRows } from "@/lib/useClampRows";
import { usePaywall } from "@/lib/paywall";
import { SEDES } from "@/lib/types";
import type {
  CatedraOpcion,
  MateriaOpciones,
  MateriaSeleccionada,
  ProfesorRating,
} from "@/lib/types";

interface Props {
  nombre: string;
  // Materia anual: se cursa todo el año y el alumno ya está en una comisión
  // concreta, así que cátedra y comisión no se gatean.
  anual: boolean;
  seleccion: MateriaSeleccionada;
  onChange: (s: MateriaSeleccionada) => void;
  onRemove: () => void;
}

export function MateriaCard({ nombre, anual, seleccion, onChange, onRemove }: Props) {
  const { isPaid, isLoading: subLoading } = useSubscription();
  const openPaywall = usePaywall();
  const [opciones, setOpciones] = useState<MateriaOpciones | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getMateriaOpciones(seleccion.codigo)
      .then((d) => {
        if (!cancelled) setOpciones(d);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [seleccion.codigo]);

  // El endpoint devuelve también las cátedras que ya no se dictan (las necesita
  // el diálogo de reseñas). Para armar planes sólo sirven las vigentes, y como
  // los universos de profesor y sede se derivan de acá, filtrar en este único
  // punto alcanza para las tres dimensiones.
  const catedrasVigentes = useMemo(
    () => opciones?.catedras.filter((c) => c.vigente) ?? [],
    [opciones]
  );

  // Filtrado de a tres (cátedra ⇄ profesor ⇄ sede): cada dimensión se acota a
  // lo compatible con las otras dos. La relación profesor↔sede vive en la
  // comisión, así que derivamos todo de la lista plana de comisiones.
  const comisiones = useMemo(() => {
    return catedrasVigentes.flatMap((c) =>
      (c.comisiones ?? []).map((cm) => ({
        catedra_id: c.id,
        codigo: cm.codigo,
        profesor: cm.profesor,
        sede: cm.sede,
      }))
    );
  }, [catedrasVigentes]);

  // Con una comisión fijada, profesor y sede quedan determinados por ella: el
  // resto no aplica y se oculta en vez de listarse en gris (serían decenas).
  const comisionesVisibles = useMemo(() => {
    const codigo = seleccion.comision_codigo ?? null;
    if (codigo == null) return comisiones;
    return comisiones.filter(
      (c) => c.codigo === codigo && c.catedra_id === seleccion.catedra_id
    );
  }, [comisiones, seleccion.comision_codigo, seleccion.catedra_id]);

  // Universos posibles para esta materia.
  const profesoresUniverse = useMemo(() => {
    const set = new Set<string>();
    comisionesVisibles.forEach((c) => c.profesor && set.add(c.profesor));
    return Array.from(set).sort();
  }, [comisionesVisibles]);

  const sedesUniverse = useMemo(() => {
    const present = new Set<string>();
    comisionesVisibles.forEach((c) => c.sede && present.add(c.sede));
    return SEDES.filter((s) => present.has(s.codigo));
  }, [comisionesVisibles]);

  // Disponibles según la selección actual (excluyendo la propia dimensión).
  const catedrasDisponibles = useMemo(() => {
    const set = new Set<number>();
    comisiones.forEach((c) => {
      const okSede = seleccion.sede == null || c.sede === seleccion.sede;
      const okProf =
        seleccion.profesores == null ||
        (c.profesor != null && seleccion.profesores.includes(c.profesor));
      if (okSede && okProf) set.add(c.catedra_id);
    });
    return set;
  }, [comisiones, seleccion.sede, seleccion.profesores]);

  const profesoresDisponibles = useMemo(() => {
    const set = new Set<string>();
    comisionesVisibles.forEach((c) => {
      const okCat =
        seleccion.catedra_id == null || c.catedra_id === seleccion.catedra_id;
      const okSede = seleccion.sede == null || c.sede === seleccion.sede;
      if (okCat && okSede && c.profesor) set.add(c.profesor);
    });
    return Array.from(set).sort();
  }, [comisionesVisibles, seleccion.catedra_id, seleccion.sede]);

  const sedesDisponibles = useMemo(() => {
    const set = new Set<string>();
    comisionesVisibles.forEach((c) => {
      const okCat =
        seleccion.catedra_id == null || c.catedra_id === seleccion.catedra_id;
      const okProf =
        seleccion.profesores == null ||
        (c.profesor != null && seleccion.profesores.includes(c.profesor));
      if (okCat && okProf && c.sede) set.add(c.sede);
    });
    return set;
  }, [comisionesVisibles, seleccion.catedra_id, seleccion.profesores]);

  // Una cátedra restaurada desde ?q= o desde el historial puede haber dejado de
  // dictarse. Sin esto el dropdown muestra "Todas" pero igual se postea el id
  // muerto a /planes, que devuelve cero planes con un cartel confuso.
  useEffect(() => {
    if (!opciones) return;
    if (seleccion.catedra_id === null) return;
    if (catedrasVigentes.some((c) => c.id === seleccion.catedra_id)) return;
    onChange({ ...seleccion, catedra_id: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opciones, catedrasVigentes]);

  // Si la cátedra/sede elegida deja profesores seleccionados fuera de lo
  // disponible, los limpio. null = todos (no hay nada que sanitizar).
  useEffect(() => {
    // Sin opciones cargadas no hay disponibles todavía y esto borraría una
    // selección legítima (p. ej. la restaurada desde ?q= al recargar).
    if (!opciones) return;
    if (seleccion.profesores === null) return;
    if (seleccion.profesores.length === 0) return;
    const validos = new Set(profesoresDisponibles);
    const filtrados = seleccion.profesores.filter((p) => validos.has(p));
    if (filtrados.length !== seleccion.profesores.length) {
      onChange({ ...seleccion, profesores: filtrados });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opciones, profesoresDisponibles]);

  // Misma idea para la sede: fijar una comisión puede dejar la sede elegida
  // fuera de lo posible, y ahí ni siquiera se muestra para poder cambiarla.
  useEffect(() => {
    if (!opciones) return;
    if (seleccion.sede == null) return;
    if (sedesDisponibles.has(seleccion.sede)) return;
    onChange({ ...seleccion, sede: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opciones, sedesDisponibles]);

  // Comisiones de la cátedra elegida (sólo materias anuales las ofrecen). El
  // código de comisión se repite entre cátedras, así que sin cátedra no hay
  // lista posible. Se deduplica por código: la fuente puede listar la misma
  // comisión en varias filas (co-titulares).
  const comisionesDeCatedra = useMemo(() => {
    if (seleccion.catedra_id == null) return [];
    const porCodigo = new Map<string, { codigo: string; profesores: string[] }>();
    comisiones.forEach((c) => {
      if (c.catedra_id !== seleccion.catedra_id) return;
      if (seleccion.sede != null && c.sede !== seleccion.sede) return;
      if (
        seleccion.profesores != null &&
        !(c.profesor != null && seleccion.profesores.includes(c.profesor))
      ) {
        return;
      }
      const entry = porCodigo.get(c.codigo) ?? { codigo: c.codigo, profesores: [] };
      if (c.profesor && !entry.profesores.includes(c.profesor)) {
        entry.profesores.push(c.profesor);
      }
      porCodigo.set(c.codigo, entry);
    });
    return Array.from(porCodigo.values()).sort((a, b) =>
      a.codigo.localeCompare(b.codigo, undefined, { numeric: true })
    );
  }, [comisiones, seleccion.catedra_id, seleccion.sede, seleccion.profesores]);

  // La comisión cuelga de la cátedra: si cambia la cátedra (o la comisión
  // guardada ya no existe ahí) la selección deja de tener sentido.
  useEffect(() => {
    if (!opciones) return;
    const actual = seleccion.comision_codigo ?? null;
    if (actual === null) return;
    if (comisionesDeCatedra.some((c) => c.codigo === actual)) return;
    onChange({ ...seleccion, comision_codigo: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opciones, comisionesDeCatedra]);

  const catedraSeleccionada = catedrasVigentes.find(
    (c) => c.id === seleccion.catedra_id
  );

  // Los toggles de "coincide con el práctico" sólo tienen sentido donde hay
  // obligación: sin ella el teórico ya es libre y el seminario es optativo.
  // Con cátedra elegida manda la suya; si no, alcanza con que alguna la tenga.
  const obligaTeorico = catedraSeleccionada
    ? catedraSeleccionada.obliga_teorico === true
    : catedrasVigentes.some((c) => c.obliga_teorico);
  const obligaSeminario = catedraSeleccionada
    ? catedraSeleccionada.obliga_seminario === true
    : catedrasVigentes.some((c) => c.obliga_seminario);

  // Cambiar de cátedra puede dejar un toggle prendido sin nada que desatar: así
  // quedaría marcando el request como Pro sin cambiar ningún plan.
  useEffect(() => {
    if (!opciones) return;
    const patch: Partial<MateriaSeleccionada> = {};
    if (seleccion.teorico_libre && !obligaTeorico) patch.teorico_libre = false;
    if (seleccion.seminario_libre && !obligaSeminario) {
      patch.seminario_libre = false;
    }
    if (Object.keys(patch).length > 0) onChange({ ...seleccion, ...patch });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opciones, obligaTeorico, obligaSeminario]);

  // En materias anuales cátedra y comisión son gratis; el resto sigue Pro.
  const libre = isPaid || anual;

  // Materia agregada desde una URL o un historial viejos, ya discontinuada.
  const sinOferta = !!opciones && catedrasVigentes.length === 0;

  // Desktop (≥lg) muestra la fila de selectores entera y difumina la de los
  // toggles; abajo de eso, dos campos y el tercero cortado al medio.
  const isLg = useIsWide(1024);
  const {
    containerRef,
    expanded,
    setExpanded,
    collapsedHeight,
    clamp,
  } = useClampRows(isLg ? 1 : 2, [
    opciones,
    anual,
    obligaTeorico,
    obligaSeminario,
    subLoading,
  ]);

  return (
    <div className="rounded-xl border border-border bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-semibold leading-tight">{nombre}</h3>
        <button
          type="button"
          onClick={onRemove}
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          title="Quitar materia"
        >
          <X className="size-4" />
        </button>
      </div>

      {loading && (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" />
          Cargando opciones...
        </div>
      )}

      {error && (
        <p className="mt-3 text-xs text-destructive">{error}</p>
      )}

      {sinOferta && (
        <p className="mt-3 text-xs text-amber-700">
          Esta materia no se dicta este cuatrimestre. Quitala para poder generar
          planes.
        </p>
      )}

      {opciones && !sinOferta && (
        <div className="mt-3">
        {/* El relative envuelve sólo la grilla: el difuminado se ancla a su
            borde inferior, no al del botón "Ver más". */}
        <div className="relative">
        <div
          ref={containerRef}
          style={clamp ? { maxHeight: collapsedHeight! } : undefined}
          className={
            "grid grid-cols-1 gap-2 overflow-hidden sm:grid-cols-2 " +
            (anual ? "lg:grid-cols-4" : "lg:grid-cols-3")
          }
        >
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              Cátedra
            </p>
            {subLoading ? (
              <Skeleton className="h-9 w-full rounded-lg" />
            ) : (
              <CatedraDropdown
                catedras={catedrasVigentes}
                disponibles={catedrasDisponibles}
                selected={seleccion.catedra_id}
                onSelect={(id) =>
                  onChange({ ...seleccion, catedra_id: id, comision_codigo: null })
                }
                disabled={!libre}
                onLockedClick={() => openPaywall("catedra")}
              />
            )}
          </div>
          {anual && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">
                Comisión
              </p>
              {subLoading ? (
                <Skeleton className="h-9 w-full rounded-lg" />
              ) : (
                <ComisionDropdown
                  comisiones={comisionesDeCatedra}
                  selected={seleccion.comision_codigo ?? null}
                  onSelect={(codigo) =>
                    onChange({ ...seleccion, comision_codigo: codigo })
                  }
                  sinCatedra={seleccion.catedra_id == null}
                />
              )}
            </div>
          )}
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              Profesores
            </p>
            {subLoading ? (
              <Skeleton className="h-9 w-full rounded-lg" />
            ) : (
              <ProfesoresDropdown
                profesores={profesoresUniverse}
                disponibles={profesoresDisponibles}
                ratings={opciones.profesores_rating}
                selected={seleccion.profesores}
                onChange={(profs) => onChange({ ...seleccion, profesores: profs })}
                catedraLabel={catedraSeleccionada?.titular ?? null}
                disabled={!isPaid}
                onLockedClick={() => openPaywall("profesores")}
              />
            )}
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              Sede
            </p>
            {subLoading ? (
              <Skeleton className="h-9 w-full rounded-lg" />
            ) : (
              <SedeDropdown
                sedes={sedesUniverse}
                disponibles={sedesDisponibles}
                selected={seleccion.sede ?? null}
                onSelect={(sede) => onChange({ ...seleccion, sede })}
                disabled={!isPaid}
                onLockedClick={() => openPaywall("filtros")}
              />
            )}
          </div>
          {/* Los toggles van en su propia fila (col-span-full): media card cada
              uno de sm para arriba —sin importar en cuántas columnas esté la
              grilla de selectores, y con uno solo visible ocupa la mitad igual—
              y apilados a ancho completo en mobile, como los selectores. */}
          {(obligaTeorico || obligaSeminario) && (
            <div className="col-span-full grid grid-cols-1 gap-2 sm:grid-cols-2">
              {obligaTeorico && (
                <ToggleCoincide
                  titulo="Teórico"
                  label="Usar teórico obligatorio"
                  loading={subLoading}
                  checked={!seleccion.teorico_libre}
                  onChange={(v) => onChange({ ...seleccion, teorico_libre: !v })}
                  locked={!isPaid}
                  onLockedClick={() => openPaywall("filtros")}
                  lockedTitle="Hacete Pro para combinar la comisión con cualquier teórico"
                />
              )}
              {obligaSeminario && (
                <ToggleCoincide
                  titulo="Seminario"
                  label="Usar seminario obligatorio"
                  loading={subLoading}
                  checked={!seleccion.seminario_libre}
                  onChange={(v) =>
                    onChange({ ...seleccion, seminario_libre: !v })
                  }
                  locked={!isPaid}
                  onLockedClick={() => openPaywall("filtros")}
                  lockedTitle="Hacete Pro para combinar la comisión con cualquier seminario"
                />
              )}
            </div>
          )}
        </div>
        {clamp && (
          <button
            type="button"
            aria-label="Ver todos los filtros"
            onClick={() => setExpanded(true)}
            className="absolute inset-x-0 bottom-0 h-12 cursor-pointer bg-gradient-to-t from-white to-transparent"
          />
        )}
        </div>
        {collapsedHeight != null && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-2 flex items-center gap-1 text-xs font-medium text-primary hover:underline"
          >
            {expanded ? (
              <>
                <ChevronUp className="size-3.5" />
                Ver menos
              </>
            ) : (
              <>
                <ChevronDown className="size-3.5" />
                Ver más
              </>
            )}
          </button>
        )}
        </div>
      )}
    </div>
  );
}

// Toggle "usar el teórico/seminario obligatorio". Prendido (default) es el
// comportamiento de siempre; apagado desata la comisión de su obligado.
function ToggleCoincide({
  titulo,
  label,
  checked,
  onChange,
  loading,
  locked,
  onLockedClick,
  lockedTitle,
}: {
  titulo: string;
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  loading?: boolean;
  locked?: boolean;
  onLockedClick?: () => void;
  lockedTitle?: string;
}) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">{titulo}</p>
      {loading ? (
        <Skeleton className="h-9 w-full rounded-lg" />
      ) : (
        // El overlay va como hermano y no envolviendo al Switch: un botón dentro
        // de otro botón no es HTML válido.
        <div className="relative">
          <label
            title={locked ? lockedTitle : undefined}
            className={
              "flex h-9 w-full items-center gap-2 rounded-lg border border-input px-3 text-xs font-medium transition-colors max-sm:min-h-[44px] " +
              (locked
                ? "bg-muted/40 text-muted-foreground"
                : "cursor-pointer bg-white hover:bg-accent")
            }
          >
            <Switch
              checked={checked}
              onCheckedChange={onChange}
              disabled={locked}
              className="shrink-0 scale-90"
            />
            <span className="flex-1 truncate">{label}</span>
            {locked && (
              <Gem className="size-3.5 shrink-0 text-[#EC990B]" />
            )}
          </label>
          {locked && onLockedClick && (
            <button
              type="button"
              onClick={onLockedClick}
              aria-label="Hacete Pro para usar este filtro"
              className="absolute inset-0 cursor-pointer rounded-lg"
            />
          )}
        </div>
      )}
    </div>
  );
}

// Línea de metadatos de una opción de cátedra: estrellas de reseñas (si tiene) +
// cantidad de profesores. Las estrellas ayudan a decidir cátedra al armar el plan.
function CatedraOptionMeta({ c }: { c: CatedraOpcion }) {
  return (
    <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted-foreground">
      {c.review_count > 0 ? (
        <span className="flex items-center gap-1">
          <StarRating value={c.avg_rating ?? 0} size={12} />
          <span className="font-medium text-foreground">
            {c.avg_rating?.toFixed(1)}
          </span>
          <span>({c.review_count})</span>
        </span>
      ) : (
        <span>Sin reseñas</span>
      )}
      <span aria-hidden className="text-muted-foreground/40">
        ·
      </span>
      <span>{c.profesores.length} prof. en comisiones</span>
    </span>
  );
}

function CatedraDropdown({
  catedras,
  disponibles,
  selected,
  onSelect,
  disabled,
  onLockedClick,
}: {
  catedras: CatedraOpcion[];
  disponibles: Set<number>;
  selected: number | null;
  onSelect: (id: number | null) => void;
  disabled?: boolean;
  onLockedClick?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const isWide = useIsWide();
  const sel = catedras.find((c) => c.id === selected);
  const habilitadas = catedras.filter((c) => disponibles.has(c.id));
  const noDisponibles = catedras.filter((c) => !disponibles.has(c.id));
  const label = sel
    ? `Cát ${sel.numero ?? sel.id}${sel.titular ? ` · ${sel.titular}` : ""}`
    : `Todas (${catedras.length})`;

  if (disabled) {
    return (
      <button
        type="button"
        onClick={onLockedClick}
        title="Hacete Pro para elegir una cátedra específica"
        className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-muted/40 px-3 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-muted max-sm:min-h-[44px]"
      >
        <GraduationCap className="size-3.5 shrink-0" />
        <span className="flex-1 truncate">{label}</span>
        <Gem className="size-3.5 shrink-0 text-[#EC990B]" />
      </button>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-white px-3 text-left text-xs font-medium transition-colors hover:bg-accent max-sm:min-h-[44px]"
        >
          <GraduationCap className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="flex-1 truncate">{label}</span>
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[min(20rem,calc(100vw-2rem))] p-1"
        align={isWide ? "start" : "center"}
      >
        <button
          type="button"
          onClick={() => {
            onSelect(null);
            setOpen(false);
          }}
          className={
            "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent max-sm:min-h-[44px] " +
            (selected === null ? "bg-accent font-medium" : "")
          }
        >
          <span>Todas las cátedras</span>
          <span className="ml-auto text-xs text-muted-foreground">
            {catedras.length}
          </span>
        </button>
        <Separator className="my-1" />
        {habilitadas.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => {
              onSelect(c.id);
              setOpen(false);
            }}
            className={
              "flex w-full flex-col items-start gap-0.5 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent max-sm:min-h-[44px] " +
              (selected === c.id ? "bg-accent" : "")
            }
          >
            <span className="font-medium">
              Cát {c.numero ?? c.id}
              {c.titular ? <> · <span className="font-normal">{c.titular}</span></> : null}
            </span>
            <CatedraOptionMeta c={c} />
          </button>
        ))}
        {noDisponibles.length > 0 && (
          <>
            <Separator className="my-1" />
            <p className="px-2 py-1 text-xs text-muted-foreground">
              No disponibles para la selección actual
            </p>
            {noDisponibles.map((c) => (
              <button
                key={c.id}
                type="button"
                disabled
                className="flex w-full cursor-not-allowed flex-col items-start gap-0.5 rounded-md px-2 py-2 text-left text-sm opacity-50"
              >
                <span className="font-medium">
                  Cát {c.numero ?? c.id}
                  {c.titular ? <> · <span className="font-normal">{c.titular}</span></> : null}
                </span>
                <CatedraOptionMeta c={c} />
              </button>
            ))}
          </>
        )}
      </PopoverContent>
    </Popover>
  );
}

// Nro de comisión dentro de la cátedra elegida. Sólo aparece en materias
// anuales, donde el alumno ya está cursando una comisión concreta y quiere
// bloquear ese horario exacto. Gratis para todos, como la cátedra en esas materias.
function ComisionDropdown({
  comisiones,
  selected,
  onSelect,
  sinCatedra,
}: {
  comisiones: Array<{ codigo: string; profesores: string[] }>;
  selected: string | null;
  onSelect: (codigo: string | null) => void;
  sinCatedra: boolean;
}) {
  const [open, setOpen] = useState(false);
  const isWide = useIsWide();

  if (sinCatedra) {
    return (
      <div
        title="Elegí una cátedra para poder fijar la comisión"
        className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-muted/40 px-3 text-left text-xs font-medium text-muted-foreground max-sm:min-h-[44px]"
      >
        <Hash className="size-3.5 shrink-0" />
        <span className="flex-1 truncate">Elegí una cátedra primero</span>
      </div>
    );
  }

  const label = selected
    ? `Com ${selected}`
    : `Todas (${comisiones.length})`;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-white px-3 text-left text-xs font-medium transition-colors hover:bg-accent max-sm:min-h-[44px]"
        >
          <Hash className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="flex-1 truncate">{label}</span>
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[min(20rem,calc(100vw-2rem))] p-1"
        align={isWide ? "start" : "center"}
      >
        <button
          type="button"
          onClick={() => {
            onSelect(null);
            setOpen(false);
          }}
          className={
            "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent max-sm:min-h-[44px] " +
            (selected === null ? "bg-accent font-medium" : "")
          }
        >
          <span>Todas las comisiones</span>
          <span className="ml-auto text-xs text-muted-foreground">
            {comisiones.length}
          </span>
        </button>
        <Separator className="my-1" />
        {/* Una cátedra puede tener 60 comisiones: sin el scroll el popover se
            sale de la pantalla (en mobile no hay forma de llegar al final). */}
        <div className="max-h-72 overflow-y-auto pr-1">
          {comisiones.length === 0 ? (
            <p className="py-4 text-center text-xs text-muted-foreground">
              No hay comisiones para la selección actual.
            </p>
          ) : (
            comisiones.map((c) => (
              <button
                key={c.codigo}
                type="button"
                onClick={() => {
                  onSelect(c.codigo);
                  setOpen(false);
                }}
                className={
                  "flex w-full flex-col items-start gap-0.5 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent max-sm:min-h-[44px] " +
                  (selected === c.codigo ? "bg-accent" : "")
                }
              >
                <span className="font-medium">Com {c.codigo}</span>
                {c.profesores.length > 0 && (
                  <span className="text-xs text-muted-foreground">
                    {c.profesores.join(" · ")}
                  </span>
                )}
              </button>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

// Estrella única + promedio para un profesor (sólo si tiene reseñas).
function ProfesorRatingBadge({ rating }: { rating?: ProfesorRating }) {
  if (!rating || rating.review_count === 0 || rating.avg_rating === null) {
    return null;
  }
  return (
    <span className="flex shrink-0 items-center gap-0.5 text-xs text-muted-foreground">
      <Star className="size-3 fill-amber-400 text-amber-400" strokeWidth={1.5} />
      <span className="font-medium text-foreground">
        {rating.avg_rating.toFixed(1)}
      </span>
    </span>
  );
}

function ProfesoresDropdown({
  profesores,
  disponibles,
  ratings,
  selected,
  onChange,
  catedraLabel,
  disabled,
  onLockedClick,
}: {
  profesores: string[];
  disponibles: string[];
  ratings: Record<string, ProfesorRating>;
  selected: string[] | null;
  onChange: (profs: string[] | null) => void;
  catedraLabel: string | null;
  disabled?: boolean;
  onLockedClick?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const isWide = useIsWide();
  const disponiblesSet = new Set(disponibles);
  const noDisponibles = profesores.filter((p) => !disponiblesSet.has(p));

  // Estados (sobre los profesores disponibles, que son los seleccionables):
  //   selected === null            -> todos (sentinel)
  //   selected.length === 0        -> ninguno explícito
  //   selected cubre los disponibles -> todos materializado
  //   subset                       -> selección parcial
  const allSelected =
    selected === null ||
    (selected.length === disponibles.length && disponibles.length > 0);
  const noneSelected = selected !== null && selected.length === 0;

  const label = allSelected
    ? `Todos (${disponibles.length})`
    : noneSelected
    ? "Ninguno"
    : `${selected!.length} de ${disponibles.length}`;

  if (disabled) {
    return (
      <button
        type="button"
        onClick={onLockedClick}
        title="Hacete Pro para filtrar profesores"
        className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-muted/40 px-3 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-muted max-sm:min-h-[44px]"
      >
        <Users className="size-3.5 shrink-0" />
        <span className="flex-1 truncate">{label}</span>
        <Gem className="size-3.5 shrink-0 text-[#EC990B]" />
      </button>
    );
  }

  function toggle(prof: string) {
    if (selected === null) {
      // Estaban todos implícitamente; pasamos a modo explícito sin éste.
      onChange(disponibles.filter((p) => p !== prof));
      return;
    }
    if (selected.includes(prof)) {
      onChange(selected.filter((p) => p !== prof));
    } else {
      onChange([...selected, prof]);
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-white px-3 text-left text-xs font-medium transition-colors hover:bg-accent max-sm:min-h-[44px]"
        >
          <Users className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="flex-1 truncate">{label}</span>
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[min(20rem,calc(100vw-2rem))] p-2"
        align={isWide ? "start" : "center"}
      >
        <p className="px-2 pb-2 text-xs text-muted-foreground">
          {catedraLabel
            ? `Profesores de ${catedraLabel}.`
            : "Profesores de todas las cátedras."}
        </p>
        <div className="flex items-center justify-end gap-2 px-1 pb-2">
          <button
            type="button"
            onClick={() =>
              allSelected ? onChange([]) : onChange(null)
            }
            disabled={disponibles.length === 0}
            className="text-xs text-primary disabled:cursor-not-allowed disabled:text-muted-foreground"
          >
            {allSelected ? "Deseleccionar todos" : "Seleccionar todos"}
          </button>
        </div>
        <div className="max-h-72 overflow-y-auto pr-1">
          {disponibles.length === 0 && noDisponibles.length === 0 ? (
            <p className="py-4 text-center text-xs text-muted-foreground">
              No hay profesores disponibles.
            </p>
          ) : (
            <>
              {disponibles.map((p) => {
                const isSelected =
                  selected === null ? true : selected.includes(p);
                return (
                  <label
                    key={p}
                    className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent max-sm:min-h-[44px]"
                  >
                    <Checkbox
                      checked={isSelected}
                      onCheckedChange={() => toggle(p)}
                    />
                    <span className="flex-1 truncate">{p}</span>
                    <ProfesorRatingBadge rating={ratings[p]} />
                  </label>
                );
              })}
              {noDisponibles.length > 0 && (
                <>
                  <Separator className="my-1" />
                  <p className="px-2 py-1 text-xs text-muted-foreground">
                    No disponibles para la selección actual
                  </p>
                  {noDisponibles.map((p) => (
                    <label
                      key={p}
                      className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm opacity-50"
                    >
                      <Checkbox checked={false} disabled />
                      <span className="flex-1 truncate">{p}</span>
                      <ProfesorRatingBadge rating={ratings[p]} />
                    </label>
                  ))}
                </>
              )}
            </>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function SedeDropdown({
  sedes,
  disponibles,
  selected,
  onSelect,
  disabled,
  onLockedClick,
}: {
  sedes: Array<{ codigo: string; nombre: string }>;
  disponibles: Set<string>;
  selected: string | null;
  onSelect: (sede: string | null) => void;
  disabled?: boolean;
  onLockedClick?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const isWide = useIsWide();
  const habilitadas = sedes.filter((s) => disponibles.has(s.codigo));
  const noDisponibles = sedes.filter((s) => !disponibles.has(s.codigo));
  // Para el label usamos SEDES (lookup completo) por si la selección quedó
  // en una sede que ya no aparece entre las de la materia.
  const sel = SEDES.find((s) => s.codigo === selected);
  const label = sel ? `${sel.nombre} (${sel.codigo})` : "Cualquiera";

  if (disabled) {
    return (
      <button
        type="button"
        onClick={onLockedClick}
        title="Hacete Pro para forzar una sede"
        className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-muted/40 px-3 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-muted max-sm:min-h-[44px]"
      >
        <MapPin className="size-3.5 shrink-0" />
        <span className="flex-1 truncate">{label}</span>
        <Gem className="size-3.5 shrink-0 text-[#EC990B]" />
      </button>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-white px-3 text-left text-xs font-medium transition-colors hover:bg-accent max-sm:min-h-[44px]"
        >
          <MapPin className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="flex-1 truncate">{label}</span>
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[min(20rem,calc(100vw-2rem))] p-1"
        align={isWide ? "start" : "center"}
      >
        <button
          type="button"
          onClick={() => {
            onSelect(null);
            setOpen(false);
          }}
          className={
            "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent max-sm:min-h-[44px] " +
            (selected === null ? "bg-accent font-medium" : "")
          }
        >
          <span>Cualquier sede</span>
        </button>
        <Separator className="my-1" />
        {habilitadas.map((s) => (
          <button
            key={s.codigo}
            type="button"
            onClick={() => {
              onSelect(s.codigo);
              setOpen(false);
            }}
            className={
              "flex w-full items-center justify-between gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent max-sm:min-h-[44px] " +
              (selected === s.codigo ? "bg-accent font-medium" : "")
            }
          >
            <span>{s.nombre}</span>
            <span className="text-xs text-muted-foreground">{s.codigo}</span>
          </button>
        ))}
        {noDisponibles.length > 0 && (
          <>
            <Separator className="my-1" />
            <p className="px-2 py-1 text-xs text-muted-foreground">
              No disponibles para la selección actual
            </p>
            {noDisponibles.map((s) => (
              <div
                key={s.codigo}
                className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-2 text-sm opacity-50"
              >
                <span>{s.nombre}</span>
                <span className="text-xs text-muted-foreground">{s.codigo}</span>
              </div>
            ))}
          </>
        )}
      </PopoverContent>
    </Popover>
  );
}
