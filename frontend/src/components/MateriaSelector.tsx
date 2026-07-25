import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ErrorState";
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerTrigger,
} from "@/components/ui/drawer";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { MateriaCard } from "@/components/MateriaCard";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useCareer } from "@/lib/career";
import type { MateriaListItem, MateriaSeleccionada } from "@/lib/types";

interface SeleccionConNombre extends MateriaSeleccionada {
  nombre: string;
}

interface Props {
  selected: SeleccionConNombre[];
  onChange: (materias: SeleccionConNombre[]) => void;
}

// El default de cmdk usa command-score (fuzzy con tildes y rankings raros);
// con esto hacemos un substring match sobre texto normalizado, que es lo que
// el usuario espera al buscar materias.
function normalizar(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function filtrarMateria(value: string, search: string): number {
  if (!search) return 1;
  const v = normalizar(value);
  const s = normalizar(search.trim());
  if (!s) return 1;
  if (v.startsWith(s)) return 1;
  if (v.includes(s)) return 0.8;
  // Fallback: que aparezcan todas las palabras del search en cualquier orden.
  const palabras = s.split(/\s+/).filter(Boolean);
  if (palabras.length > 1 && palabras.every((p) => v.includes(p))) return 0.5;
  return 0;
}

export function MateriaSelector({ selected, onChange }: Props) {
  const { carrera } = useCareer();
  const [open, setOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [materias, setMaterias] = useState<MateriaListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [query, setQuery] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const rowRef = useRef<HTMLDivElement>(null);
  const [popoverWidth, setPopoverWidth] = useState<number | null>(null);
  const [rowHeight, setRowHeight] = useState(0);
  const [isWide, setIsWide] = useState(false);

  // Scroll al tope cada vez que cambia el query. En un useEffect (no en
  // onValueChange) para correr DESPUÉS de que cmdk filtró y reordenó.
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = 0;
  }, [query]);

  // El popover se renderiza en un portal, por eso no hereda el ancho del Card.
  // Lo medimos para que el contenedor de búsqueda matchee el de seleccionadas
  // en desktop. En mobile la columna no tiene un "match" útil — usamos un ancho
  // estándar centrado.
  useEffect(() => {
    const el = wrapperRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setPopoverWidth(el.offsetWidth));
    ro.observe(el);
    setPopoverWidth(el.offsetWidth);
    return () => ro.disconnect();
  }, []);

  // En mobile el popover baja desde el borde superior de la fila (debajo del
  // título "Materias") tapando el botón. Como side="bottom" lo ancla al borde
  // inferior de la fila, lo subimos con un sideOffset negativo = alto de la fila.
  useEffect(() => {
    const el = rowRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setRowHeight(el.offsetHeight));
    ro.observe(el);
    setRowHeight(el.offsetHeight);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 821px)");
    const update = () => setIsWide(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  // Se incrementa en cada carga; ignoramos respuestas de cargas ya superadas
  // (cambio de carrera o reintento) para no pisar el estado con data vieja.
  const loadIdRef = useRef(0);
  const loadMaterias = useCallback(() => {
    // Esperar a tener carrera (usuario logueado: hasta que cargue el profile).
    if (!carrera) {
      setMaterias([]);
      setLoading(true);
      return;
    }
    const loadId = ++loadIdRef.current;
    setLoading(true);
    setError(false);
    api
      .listMateriasCached(carrera)
      .then((d) => {
        if (loadIdRef.current === loadId) setMaterias(d);
      })
      .catch(() => {
        if (loadIdRef.current === loadId) setError(true);
      })
      .finally(() => {
        if (loadIdRef.current === loadId) setLoading(false);
      });
  }, [carrera]);

  useEffect(() => {
    loadMaterias();
  }, [loadMaterias]);

  const selectedIds = useMemo(
    () => new Set(selected.map((m) => m.codigo)),
    [selected]
  );

  const disponibles = useMemo(
    () => materias.filter((m) => !selectedIds.has(m.codigo)),
    [materias, selectedIds]
  );

  function add(m: MateriaListItem) {
    onChange([
      { codigo: m.codigo, nombre: m.nombre, catedra_id: null, profesores: null, sede: null },
      ...selected,
    ]);
    setOpen(false);
    setDrawerOpen(false);
  }

  function update(codigo: number, patch: Partial<MateriaSeleccionada>) {
    onChange(
      selected.map((m) =>
        m.codigo === codigo ? { ...m, ...patch } : m
      )
    );
  }

  function remove(codigo: number) {
    onChange(selected.filter((m) => m.codigo !== codigo));
  }

  const addButtonContent = loading ? (
    <Loader2 className="size-3.5 animate-spin" />
  ) : (
    <Plus className="size-3.5" />
  );

  const materiasCommand = (listClassName?: string, drawer = false) => (
    <Command
      shouldFilter
      filter={filtrarMateria}
      className={cn(
        "rounded-none wide:rounded-lg",
        drawer &&
          "[&_[cmdk-input-wrapper]]:mb-2 [&_[cmdk-input-wrapper]]:ml-4 [&_[cmdk-input-wrapper]]:mr-[4.25rem] [&_[cmdk-input-wrapper]]:mt-4 [&_[cmdk-input-wrapper]]:h-11 [&_[cmdk-input-wrapper]]:rounded-full [&_[cmdk-input-wrapper]]:border [&_[cmdk-input-wrapper]]:border-input [&_[cmdk-input-wrapper]]:bg-white [&_[cmdk-input-wrapper]]:pr-3"
      )}
    >
      <CommandInput
        placeholder="Buscar materia..."
        className={cn("pr-12 wide:pr-0", drawer && "text-base")}
        onValueChange={setQuery}
      />
      <CommandList ref={listRef} className={listClassName}>
        {loading && (
          <div className="py-6 text-center text-sm text-muted-foreground">
            Cargando materias...
          </div>
        )}
        {error && (
          <ErrorState
            title="No pudimos cargar las materias"
            description="Revisá tu conexión y volvé a intentar."
            onRetry={loadMaterias}
            retrying={loading}
            className="py-6"
          />
        )}
        {!loading && !error && (
          <>
            <CommandEmpty>No se encontraron materias.</CommandEmpty>
            <CommandGroup>
              {disponibles.map((m) => (
                <CommandItem
                  key={m.codigo}
                  value={`${m.nombre} ${m.codigo}`}
                  onSelect={() => add(m)}
                >
                  <span className="line-clamp-2 flex-1">{m.nombre}</span>
                  <span className="ml-2 shrink-0 text-xs text-muted-foreground">
                    {m.cant_catedras}{" "}
                    {m.cant_catedras === 1 ? "cát." : "cáts."}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
      </CommandList>
    </Command>
  );

  const triggerRow = (
    <div
      ref={rowRef}
      className="flex shrink-0 flex-wrap items-center justify-between gap-2"
    >
      <div
        className={cn(
          "flex items-center gap-2 text-sm text-muted-foreground",
          selected.length === 0 && "hidden wide:flex",
        )}
      >
        {loading && selected.length === 0 && (
          <Loader2 className="size-4 animate-spin" />
        )}
        <span>
          {loading && selected.length === 0
            ? "Cargando materias…"
            : selected.length === 0
            ? "Ninguna materia seleccionada"
            : `${selected.length} ${selected.length === 1 ? "materia" : "materias"}`}
        </span>
      </div>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={loading}
          className={cn(
            "hidden wide:inline-flex",
            selected.length === 0 && "wide:w-auto"
          )}
        >
          {addButtonContent}
          Agregar materia
        </Button>
      </PopoverTrigger>
      <DrawerTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={loading}
          className={cn("wide:hidden", selected.length === 0 && "w-full")}
        >
          {addButtonContent}
          Agregar materia
        </Button>
      </DrawerTrigger>
    </div>
  );

  return (
    <div ref={wrapperRef} className="flex flex-col gap-3 wide:h-full">
      <Drawer open={drawerOpen} onOpenChange={setDrawerOpen}>
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverAnchor asChild>{triggerRow}</PopoverAnchor>
          <PopoverContent
            className="hidden p-0 wide:block"
            side="bottom"
            sideOffset={isWide ? 8 : -rowHeight}
            avoidCollisions={false}
            align={isWide ? "end" : "center"}
            style={
              isWide && popoverWidth
                ? { width: popoverWidth }
                : { width: "min(520px, calc(100vw - 2rem))" }
            }
          >
            {materiasCommand()}
          </PopoverContent>
        </Popover>
        <DrawerContent
          showHandle={false}
          // Sin autofocus: si enfocamos el input, el teclado virtual salta y
          // tapa media pantalla antes de que el usuario decida si va a buscar.
          onOpenAutoFocus={(e) => e.preventDefault()}
          className="h-[calc(100dvh-16px)] max-h-[calc(100dvh-16px)] overflow-hidden rounded-t-2xl border-0"
        >
          <div className="relative flex min-h-0 flex-1 flex-col">
            {materiasCommand("max-h-none flex-1 pb-4", true)}
            <DrawerClose asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Cerrar"
                className="absolute right-4 top-4 size-11 rounded-full border border-input bg-white"
              >
                <X className="size-4" />
              </Button>
            </DrawerClose>
          </div>
        </DrawerContent>
      </Drawer>

      {selected.length > 0 && (
        <div className="space-y-2 wide:min-h-0 wide:flex-1 wide:overflow-y-auto">
          {selected.map((m) => (
            <MateriaCard
              key={m.codigo}
              nombre={m.nombre}
              seleccion={m}
              onChange={(s) => update(m.codigo, s)}
              onRemove={() => remove(m.codigo)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
