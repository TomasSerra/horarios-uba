import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Sparkles,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Gem,
  XCircle,
  Heart,
  ChevronDown,
  Filter,
  BookOpen,
} from "lucide-react";
import mpIcon from "@/assets/mp-icon.png";
import { useAuth } from "@/lib/useAuth";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CarreraSelector } from "@/components/CarreraSelector";
import { FavoritoFormDialog } from "@/components/FavoritoFormDialog";
import { MateriaSelector } from "@/components/MateriaSelector";
import { ErrorState } from "@/components/ErrorState";
import { RestriccionesPanel } from "@/components/RestriccionesPanel";
import { CalendarioPlan } from "@/components/CalendarioPlan";
import { CalendarioPlanSkeleton } from "@/components/CalendarioPlanSkeleton";
import { PlanNavigator } from "@/components/PlanNavigator";
import { Header } from "@/components/Header";
import { Seo } from "@/components/Seo";
import { HistorialPopover } from "@/components/HistorialPopover";
import { FREE_MAX_PLANES, PRO_MAX_PLANES } from "@/components/PaywallProvider";
import { api } from "@/lib/api";
import {
  pushHistory,
  entryUsesProFilters,
  seleccionUsesProFilters,
} from "@/lib/planHistory";
import { useSubscription } from "@/lib/useSubscription";
import { markProActive, meQueryKey } from "@/lib/useMe";
import { useCareer } from "@/lib/career";
import { usePaywall } from "@/lib/paywall";
import { useAlert } from "@/lib/alert";
import {
  DIAS,
  type FavoriteFilters,
  type FranjaExcluida,
  type MateriaSeleccionada,
  type Plan,
  type PlanHistoryEntry,
  type PlanResponse,
} from "@/lib/types";
import { useVisualViewportStick } from "@/lib/useVisualViewportStick";

interface SeleccionConNombre extends MateriaSeleccionada {
  nombre: string;
  anual: boolean;
}

// Selección → lo que viaja a /planes. Se usa también para la firma que decide si
// "Generar" está habilitado, así que las claves van explícitas y en orden fijo:
// dos objetos con las mismas claves en distinto orden dan JSON.stringify distinto.
function toMateriaRequest(m: SeleccionConNombre): MateriaSeleccionada {
  return {
    codigo: m.codigo,
    catedra_id: m.catedra_id,
    profesores: m.profesores,
    sede: m.sede ?? null,
    comision_codigo: m.comision_codigo ?? null,
    teorico_libre: m.teorico_libre ?? false,
    seminario_libre: m.seminario_libre ?? false,
  };
}

interface PagoErrorState {
  status: string | null;
  statusDetail: string | null;
}

function PagoErrorDialog({
  state,
  onClose,
}: {
  state: PagoErrorState | null;
  onClose: () => void;
}) {
  const { getAccessTokenSilently } = useAuth();
  const showAlert = useAlert();
  const [retrying, setRetrying] = useState(false);

  async function reintentar() {
    setRetrying(true);
    try {
      const token = await getAccessTokenSilently();
      if (!token) throw new Error("No token");
      const { init_point } = await api.postCheckout(token);
      window.location.href = init_point;
    } catch (e) {
      setRetrying(false);
      showAlert({
        variant: "error",
        title: "No se pudo iniciar el pago",
        message: (e as Error).message,
      });
    }
  }

  const status = state?.status;
  const statusDetail = state?.statusDetail;
  const hasStatus = status && status !== "null";
  const hasDetail = statusDetail && statusDetail !== "null";

  return (
    <Dialog open={state !== null} onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <div className="flex flex-col items-center pt-2 text-center">
          <XCircle className="size-12 text-destructive" strokeWidth={1.5} />
          <DialogHeader className="mt-3 space-y-2 sm:text-center">
            <DialogTitle className="text-center">
              El pago no se procesó
            </DialogTitle>
            <DialogDescription className="text-center">
              Mercado Pago rechazó la transacción
              {hasStatus ? ` (${status})` : ""}
              {hasDetail ? `: ${statusDetail}` : ""}. No se descontó plata.
            </DialogDescription>
          </DialogHeader>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={onClose}>
            Cerrar
          </Button>
          <Button
            onClick={reintentar}
            disabled={retrying}
            className="bg-[#EC990B] text-white hover:bg-[#EC990B]/90"
          >
            {retrying ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <img src={mpIcon} alt="" className="h-4 w-auto" />
            )}
            Reintentar pago
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const PAGO_POLL_INTERVAL_MS = 5000;
// Subido a 45s tras llevar el intervalo de poll de 2s → 5s: nos da ~9 polls
// dentro de la ventana, suficiente margen para que el webhook de MP llegue
// incluso cuando tarda 20-30s.
const PAGO_MAX_WAIT_MS = 45_000;

function PagoStatusDialog({
  externalReference,
  onClose,
}: {
  externalReference: string | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [startedAt] = useState(() => Date.now());

  const { data, error } = useQuery({
    queryKey: ["pago-status", externalReference],
    queryFn: () => {
      if (!externalReference) throw new Error("Falta external_reference");
      return api.getPagoStatus(externalReference);
    },
    enabled: !!externalReference,
    refetchInterval: (q) => {
      if (q.state.data?.status === "approved") return false;
      if (Date.now() - startedAt > PAGO_MAX_WAIT_MS) return false;
      return PAGO_POLL_INTERVAL_MS;
    },
  });

  useEffect(() => {
    if (data?.status === "approved") {
      markProActive(queryClient);
      const t = setTimeout(onClose, 1500);
      return () => clearTimeout(t);
    }
  }, [data?.status, queryClient, onClose]);

  const open = !!externalReference;
  const timedOut = Date.now() - startedAt > PAGO_MAX_WAIT_MS;

  let icon: React.ReactNode;
  let title: string;
  let body: string;
  if (error) {
    icon = (
      <AlertCircle className="size-12 text-destructive" strokeWidth={1.5} />
    );
    title = "Error confirmando el pago";
    body = (error as Error).message;
  } else if (data?.status === "approved") {
    icon = (
      <CheckCircle2 className="size-12 text-emerald-600" strokeWidth={1.5} />
    );
    title = "¡Listo! Pago acreditado";
    body = "Ya tenés acceso Pro.";
  } else if (timedOut) {
    icon = <AlertCircle className="size-12 text-amber-600" strokeWidth={1.5} />;
    title = "El pago se está acreditando";
    body =
      "Mercado Pago a veces tarda unos minutos. Cuando se acredite, vas a ver el chip Pro en el header.";
  } else {
    icon = (
      <Loader2
        className="size-12 animate-spin text-primary"
        strokeWidth={1.5}
      />
    );
    title = "Confirmando tu pago…";
    body = "Esto puede tardar unos segundos.";
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <div className="flex flex-col items-center pt-2 text-center">
          {icon}
          <DialogHeader className="mt-3 space-y-2 sm:text-center">
            <DialogTitle className="text-center">{title}</DialogTitle>
            <DialogDescription className="text-center">
              {body}
            </DialogDescription>
          </DialogHeader>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function SaveFavoriteButton({
  plan,
  filters,
  isPaid,
  onLockedClick,
}: {
  plan: Plan;
  filters: FavoriteFilters;
  isPaid: boolean;
  onLockedClick: () => void;
}) {
  const { getAccessTokenSilently } = useAuth();
  const showAlert = useAlert();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [savedId, setSavedId] = useState<number | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  // Plan distinto = botón vuelve a estado inicial.
  const planKey = useMemo(
    () =>
      JSON.stringify(
        plan.opciones.map((o) => o.cursos.map((c) => c.id).sort()),
      ),
    [plan],
  );
  const [keyAtSave, setKeyAtSave] = useState<string | null>(null);
  const isSaved = savedId !== null && keyAtSave === planKey;

  if (!isPaid) {
    return (
      <Button
        variant="outline"
        size="sm"
        onClick={onLockedClick}
        title="Hacete Pro para guardar favoritos"
      >
        <Heart className="size-4" />
        Guardar
        <Gem className="size-3.5 text-[#EC990B]" />
      </Button>
    );
  }

  // Guardar pide nombre y descripción en un modal; quitar sigue siendo directo.
  async function quitar() {
    if (savedId === null) return;
    setBusy(true);
    try {
      const token = await getAccessTokenSilently();
      await api.deleteFavorito(savedId, token);
      setSavedId(null);
      setKeyAtSave(null);
      queryClient.invalidateQueries({ queryKey: ["favoritos"] });
    } catch (e) {
      showAlert({
        variant: "error",
        title: "No se pudo eliminar",
        message: (e as Error).message,
      });
    } finally {
      setBusy(false);
    }
  }

  async function guardar(nombre: string, descripcion: string | null) {
    setBusy(true);
    try {
      const token = await getAccessTokenSilently();
      const { id } = await api.addFavorito(
        plan,
        filters,
        nombre,
        descripcion,
        token,
      );
      setSavedId(id);
      setKeyAtSave(planKey);
      setDialogOpen(false);
      queryClient.invalidateQueries({ queryKey: ["favoritos"] });
    } catch (e) {
      showAlert({
        variant: "error",
        title: "No se pudo guardar",
        message: (e as Error).message,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => (isSaved ? quitar() : setDialogOpen(true))}
        disabled={busy}
        className={
          isSaved
            ? "border-red-500 bg-red-500 text-white hover:bg-red-500/90 hover:text-white"
            : ""
        }
      >
        {busy ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <Heart className={"size-4 " + (isSaved ? "fill-current" : "")} />
        )}
        {isSaved ? "Guardado" : "Guardar"}
      </Button>
      <FavoritoFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mode="guardar"
        saving={busy}
        onSubmit={guardar}
      />
    </>
  );
}

const ALL_DIAS: string[] = [...DIAS];

// `BrushCleaning` aún no existe en lucide-react 0.460.0; inline para evitar el bump.
function BrushCleaning({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="m16 22-1-4" />
      <path d="M19 13.99a1 1 0 0 0 1-1V12a2 2 0 0 0-2-2h-3a1 1 0 0 1-1-1V4a2 2 0 0 0-4 0v5a1 1 0 0 1-1 1H6a2 2 0 0 0-2 2v.99a1 1 0 0 0 1 1" />
      <path d="M5 14h14l1.973 6.767A1 1 0 0 1 20 22H4a1 1 0 0 1-.973-1.233z" />
      <path d="m8 22 1-4" />
    </svg>
  );
}

interface UrlState {
  m: {
    c: number;
    ca: number | null;
    p: string[] | null;
    se?: string | null;
    co?: string | null;
    tl?: boolean;
    sl?: boolean;
  }[];
  d: string[];
  f: FranjaExcluida[];
  s: string[];
  b?: number | null;
  dmin?: number | null;
  dmax?: number | null;
  hmin?: number | null;
  hmax?: number | null;
  sc?: boolean;
}

function encodeUrlState(s: UrlState): string {
  return encodeURIComponent(JSON.stringify(s));
}

function decodeUrlState(raw: string): UrlState | null {
  try {
    const parsed = JSON.parse(decodeURIComponent(raw));
    if (!parsed || !Array.isArray(parsed.m)) return null;
    return parsed as UrlState;
  } catch {
    return null;
  }
}

export function Home() {
  const { isPaid, isLoading: subLoading } = useSubscription();
  const { user, isAuthenticated, getAccessTokenSilently } = useAuth();
  const showAlert = useAlert();
  const openPaywall = usePaywall();
  const queryClient = useQueryClient();
  const uid = user?.uid ?? null;

  // Si MP redirigió a /pago-error o /pago-exitoso, abrimos un dialog encima
  // de Home y limpiamos la URL para que reload no re-dispare el dialog.
  const location = useLocation();
  const navigate = useNavigate();
  const [pagoError, setPagoError] = useState<PagoErrorState | null>(null);
  const [pagoExternalRef, setPagoExternalRef] = useState<string | null>(null);
  useEffect(() => {
    if (location.pathname === "/pago-error") {
      const params = new URLSearchParams(location.search);
      setPagoError({
        status: params.get("status"),
        statusDetail: params.get("status_detail"),
      });
      navigate("/", { replace: true });
    } else if (location.pathname === "/pago-exitoso") {
      const params = new URLSearchParams(location.search);
      const ref = params.get("ref");
      if (ref) setPagoExternalRef(ref);
      navigate("/", { replace: true });
    }
  }, [location.pathname, location.search, navigate]);

  const [materias, setMaterias] = useState<SeleccionConNombre[]>([]);
  // Por default: todos los días marcados (= sin restricción).
  const [diasPermitidos, setDiasPermitidos] = useState<string[]>(ALL_DIAS);
  const [franjas, setFranjas] = useState<FranjaExcluida[]>([]);
  const [sedesPermitidas, setSedesPermitidas] = useState<string[]>([]);
  const [maxBacheHoras, setMaxBacheHoras] = useState<number | null>(null);
  const [minDiasSemana, setMinDiasSemana] = useState<number | null>(null);
  const [maxDiasSemana, setMaxDiasSemana] = useState<number | null>(null);
  const [minHorasDia, setMinHorasDia] = useState<number | null>(null);
  const [maxHorasDia, setMaxHorasDia] = useState<number | null>(null);
  const [soloCupos, setSoloCupos] = useState<boolean>(false);
  const [materiasOpen, setMateriasOpen] = useState(true);
  const [filtrosOpen, setFiltrosOpen] = useState(false);
  const [calendarioCompacto, setCalendarioCompacto] = useState<boolean>(
    () => localStorage.getItem("calendarioCompacto") === "1",
  );
  useEffect(() => {
    localStorage.setItem("calendarioCompacto", calendarioCompacto ? "1" : "0");
  }, [calendarioCompacto]);

  // Hidratar materias + filtros desde ?q=… (URL compartible) y disparar
  // generación una sola vez cuando auth/sub terminan de cargar.
  const urlLoadedRef = useRef(false);
  const calendarioRef = useRef<HTMLDivElement>(null);
  const scrollOnNextResultRef = useRef(false);
  const { isLoading: authLoading } = useAuth();
  useEffect(() => {
    if (urlLoadedRef.current) return;
    if (location.pathname !== "/") return;
    if (authLoading || subLoading) return;
    // Marcar ya como cargado: si no hay ?q= no hay nada que hidratar, y si lo
    // hay vamos a hidratar ahora. En ambos casos, los navigate() posteriores
    // de runGenerate no deben re-disparar este efecto.
    urlLoadedRef.current = true;
    const q = new URLSearchParams(location.search).get("q");
    if (!q) return;
    const decoded = decodeUrlState(q);
    if (!decoded) return;
    (async () => {
      try {
        const all = await api.listMateriasCached();
        const byCodigo = new Map(all.map((m) => [m.codigo, m]));
        // Qué es Pro depende de la materia: en las anuales cátedra y comisión
        // son libres, así que el strip necesita la lista antes de decidir.
        const esAnual = (codigo: number) => byCodigo.get(codigo)?.anual ?? false;
        // Si el usuario no es Pro pero la URL trae filtros Pro (compartida por un
        // Pro o editada a mano), strippeamos los campos Pro y avisamos. Mantenemos
        // dias_excluidos y solo_con_cupos que son free.
        const proFiltersInUrl =
          !isPaid &&
          ((decoded.f && decoded.f.length > 0) ||
            (decoded.s && decoded.s.length > 0) ||
            decoded.b != null ||
            decoded.dmin != null ||
            decoded.dmax != null ||
            decoded.hmin != null ||
            decoded.hmax != null ||
            decoded.m.some(
              (x) =>
                x.p !== null ||
                (x.se ?? null) !== null ||
                x.tl === true ||
                x.sl === true ||
                (!esAnual(x.c) &&
                  (x.ca !== null || (x.co ?? null) !== null)),
            ));
        const safeDecoded: UrlState = proFiltersInUrl
          ? {
              ...decoded,
              m: decoded.m.map((x) =>
                esAnual(x.c)
                  ? { c: x.c, ca: x.ca, p: null, se: null, co: x.co ?? null }
                  : { c: x.c, ca: null, p: null, se: null, co: null },
              ),
              // Ninguna rama copia tl/sl: son Pro en todas las materias, incluidas
              // las anuales, así que el strip los deja siempre en false.
              f: [],
              s: [],
              b: null,
              dmin: null,
              dmax: null,
              hmin: null,
              hmax: null,
            }
          : decoded;
        const seleccion: SeleccionConNombre[] = safeDecoded.m.map((x) => ({
          codigo: x.c,
          catedra_id: x.ca,
          profesores: x.p,
          sede: x.se ?? null,
          comision_codigo: x.co ?? null,
          teorico_libre: x.tl ?? false,
          seminario_libre: x.sl ?? false,
          anual: esAnual(x.c),
          nombre: byCodigo.get(x.c)?.nombre ?? `Materia ${x.c}`,
        }));
        const bache = safeDecoded.b ?? null;
        const sc = safeDecoded.sc ?? false;
        const rangos = {
          minDias: safeDecoded.dmin ?? null,
          maxDias: safeDecoded.dmax ?? null,
          minHoras: safeDecoded.hmin ?? null,
          maxHoras: safeDecoded.hmax ?? null,
        };
        setMaterias(seleccion);
        setDiasPermitidos(safeDecoded.d);
        setFranjas(safeDecoded.f);
        setSedesPermitidas(safeDecoded.s);
        setMaxBacheHoras(bache);
        setMinDiasSemana(rangos.minDias);
        setMaxDiasSemana(rangos.maxDias);
        setMinHorasDia(rangos.minHoras);
        setMaxHorasDia(rangos.maxHoras);
        setSoloCupos(sc);
        if (proFiltersInUrl) {
          showAlert({
            variant: "info",
            title: "Filtros Pro descartados",
            message:
              "Esta URL incluía filtros Pro (cátedra, profesores, franjas, sede o bache). " +
              "Como no sos Pro, generamos sin esos filtros.",
          });
        }
        await runGenerate(
          seleccion,
          safeDecoded.d,
          safeDecoded.f,
          safeDecoded.s,
          bache,
          sc,
          rangos,
        );
      } catch {
        setError(true);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, subLoading, location.pathname, location.search]);

  const [resultado, setResultado] = useState<PlanResponse | null>(null);

  useEffect(() => {
    if (
      scrollOnNextResultRef.current &&
      resultado &&
      resultado.planes.length > 0
    ) {
      scrollOnNextResultRef.current = false;
      calendarioRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }
  }, [resultado]);
  const [planIdx, setPlanIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  // Scroll también al mostrar el skeleton: apenas arranca el loading, llevamos
  // al usuario a la zona del calendario para que vea la animación.
  useEffect(() => {
    if (loading) {
      calendarioRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }
  }, [loading]);

  const [lastGeneratedSignature, setLastGeneratedSignature] = useState<
    string | null
  >(null);
  const [lastGeneratedFilters, setLastGeneratedFilters] =
    useState<FavoriteFilters | null>(null);

  // Al cambiar la carrera del usuario (no en el primer set), limpiar la
  // selección y el filtro de sedes — las materias y sedes que mostrábamos
  // ya no aplican a la nueva carrera. También limpiamos resultado/signature
  // para que no quede un calendario viejo.
  const { carrera: carreraActual } = useCareer();
  const lastCarreraRef = useRef<string | null>(null);
  useEffect(() => {
    if (!carreraActual) return;
    if (lastCarreraRef.current && lastCarreraRef.current !== carreraActual) {
      setMaterias([]);
      setSedesPermitidas([]);
      setResultado(null);
      setLastGeneratedSignature(null);
      setError(false);
    }
    lastCarreraRef.current = carreraActual;
  }, [carreraActual]);

  const currentSignature = useMemo(
    () =>
      JSON.stringify({
        materias: materias.map(toMateriaRequest),
        diasPermitidos: [...diasPermitidos].sort(),
        franjas,
        sedesPermitidas: [...sedesPermitidas].sort(),
        maxBacheHoras,
        minDiasSemana,
        maxDiasSemana,
        minHorasDia,
        maxHorasDia,
        soloCupos,
      }),
    [
      materias,
      diasPermitidos,
      franjas,
      sedesPermitidas,
      maxBacheHoras,
      minDiasSemana,
      maxDiasSemana,
      minHorasDia,
      maxHorasDia,
      soloCupos,
    ],
  );

  const sinCambios =
    lastGeneratedSignature !== null &&
    currentSignature === lastGeneratedSignature;

  // Si el form actual tiene filtros Pro y el usuario no es Pro, no dejamos
  // disparar "Generar" — el backend rechazaría con 403 igual, pero acá lo
  // anticipamos con un tooltip claro. Cubre el caso de restore-from-history
  // con filtros Pro siendo user free.
  const formUsesProFilters = seleccionUsesProFilters(
    materias,
    franjas,
    sedesPermitidas,
    maxBacheHoras,
    minDiasSemana,
    maxDiasSemana,
    minHorasDia,
    maxHorasDia,
  );
  const proFiltersBlocked = !isPaid && !subLoading && formUsesProFilters;

  // Si el usuario se vuelve Pro mientras hay un resultado topeado al límite
  // Free en pantalla, regeneramos automáticamente con el cap nuevo (100).
  // Cubre: vuelta del checkout, polling QR aprobado, y restore del historial
  // siendo Pro con un response viejo capeado a Free.
  const autoRegenFiredRef = useRef(false);
  useEffect(() => {
    autoRegenFiredRef.current = false;
  }, [currentSignature]);
  useEffect(() => {
    if (!isPaid || subLoading) return;
    if (!resultado || resultado.planes.length !== FREE_MAX_PLANES) return;
    if (!lastGeneratedFilters) return;
    if (autoRegenFiredRef.current) return;
    autoRegenFiredRef.current = true;
    void generar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPaid, subLoading, resultado, lastGeneratedFilters]);

  async function runGenerate(
    seleccion: SeleccionConNombre[],
    dias: string[],
    franjasExcl: FranjaExcluida[],
    sedes: string[],
    bache: number | null,
    solo: boolean,
    rangos: {
      minDias: number | null;
      maxDias: number | null;
      minHoras: number | null;
      maxHoras: number | null;
    },
  ) {
    if (seleccion.length === 0) return;
    setLoading(true);
    setError(false);
    setResultado(null);
    setPlanIdx(0);
    try {
      const dias_excluidos = ALL_DIAS.filter((d) => !dias.includes(d));
      const token = isAuthenticated
        ? await getAccessTokenSilently().catch(() => null)
        : null;
      const data = await api.postPlanes(
        {
          materias: seleccion.map(toMateriaRequest),
          dias_excluidos,
          franjas_excluidas: franjasExcl,
          sedes_permitidas: sedes,
          max_bache_horas: bache,
          min_dias_semana: rangos.minDias,
          max_dias_semana: rangos.maxDias,
          min_horas_dia: rangos.minHoras,
          max_horas_dia: rangos.maxHoras,
          max_planes: isPaid ? PRO_MAX_PLANES : FREE_MAX_PLANES,
          solo_con_cupos: solo,
        },
        token,
      );
      scrollOnNextResultRef.current = true;
      setResultado(data);
      const sig = JSON.stringify({
        materias: seleccion.map(toMateriaRequest),
        diasPermitidos: [...dias].sort(),
        franjas: franjasExcl,
        sedesPermitidas: [...sedes].sort(),
        maxBacheHoras: bache,
        minDiasSemana: rangos.minDias,
        maxDiasSemana: rangos.maxDias,
        minHorasDia: rangos.minHoras,
        maxHorasDia: rangos.maxHoras,
        soloCupos: solo,
      });
      setLastGeneratedSignature(sig);
      const filtersSnapshot: FavoriteFilters = {
        dias_excluidos,
        franjas_excluidas: franjasExcl,
        sedes_permitidas: sedes,
        max_bache_horas: bache,
        min_dias_semana: rangos.minDias,
        max_dias_semana: rangos.maxDias,
        min_horas_dia: rangos.minHoras,
        max_horas_dia: rangos.maxHoras,
        solo_con_cupos: solo,
        materias: seleccion.map((m) => ({
          codigo: m.codigo,
          nombre: m.nombre,
          catedra_id: m.catedra_id,
          catedra_label: null,
          profesores: m.profesores,
          sede: m.sede ?? null,
          comision_codigo: m.comision_codigo ?? null,
          teorico_libre: m.teorico_libre ?? false,
          seminario_libre: m.seminario_libre ?? false,
          anual: m.anual,
        })),
      };
      setLastGeneratedFilters(filtersSnapshot);
      if (data.planes.length > 0) {
        pushHistory(uid, {
          request: {
            materias: seleccion.map(toMateriaRequest),
            dias_excluidos,
            franjas_excluidas: franjasExcl,
            sedes_permitidas: sedes,
            max_bache_horas: bache,
            min_dias_semana: rangos.minDias,
            max_dias_semana: rangos.maxDias,
            min_horas_dia: rangos.minHoras,
            max_horas_dia: rangos.maxHoras,
            max_planes: isPaid ? PRO_MAX_PLANES : FREE_MAX_PLANES,
            solo_con_cupos: solo,
          },
          filters: filtersSnapshot,
          response: data,
        });
      }
      const q = encodeUrlState({
        m: seleccion.map((m) => ({
          c: m.codigo,
          ca: m.catedra_id,
          p: m.profesores,
          se: m.sede ?? null,
          co: m.comision_codigo ?? null,
          tl: m.teorico_libre || undefined,
          sl: m.seminario_libre || undefined,
        })),
        d: dias,
        f: franjasExcl,
        s: sedes,
        b: bache,
        dmin: rangos.minDias ?? undefined,
        dmax: rangos.maxDias ?? undefined,
        hmin: rangos.minHoras ?? undefined,
        hmax: rangos.maxHoras ?? undefined,
        sc: solo || undefined,
      });
      const search = `?q=${q}`;
      sessionStorage.setItem("horarios:last-home-search", search);
      navigate(`/${search}`, { replace: true });
    } catch (e) {
      const msg = (e as Error).message;
      if (msg.startsWith("403")) {
        // Se llega acá si: (a) la sub venció mid-sesión y el FE todavía cree
        // que es Pro, o (b) alguien intentó bypassear el gating del FE. En
        // ambos casos re-consultamos /me para resincronizar el estado y
        // mostramos un mensaje neutral.
        queryClient.invalidateQueries({ queryKey: meQueryKey(user?.uid) });
        showAlert({
          variant: "warning",
          title: "Función Pro",
          message:
            "Los filtros que estás usando son Pro. Si antes eras Pro y se te " +
            "venció la suscripción, vas a verlo reflejado en la página en un " +
            "momento. Para usar estos filtros, hacete Pro.",
        });
      } else {
        setError(true);
      }
    } finally {
      setLoading(false);
    }
  }

  function generar() {
    setMateriasOpen(false);
    setFiltrosOpen(false);
    return runGenerate(
      materias,
      diasPermitidos,
      franjas,
      sedesPermitidas,
      maxBacheHoras,
      soloCupos,
      {
        minDias: minDiasSemana,
        maxDias: maxDiasSemana,
        minHoras: minHorasDia,
        maxHoras: maxHorasDia,
      },
    );
  }

  function limpiarTodo() {
    setMaterias([]);
    setDiasPermitidos(ALL_DIAS);
    setFranjas([]);
    setSedesPermitidas([]);
    setMaxBacheHoras(null);
    setMinDiasSemana(null);
    setMaxDiasSemana(null);
    setMinHorasDia(null);
    setMaxHorasDia(null);
    setSoloCupos(false);
    setResultado(null);
    setPlanIdx(0);
    setError(false);
    setLastGeneratedSignature(null);
    setLastGeneratedFilters(null);
    sessionStorage.removeItem("horarios:last-home-search");
    navigate("/", { replace: true });
  }

  function restoreFromHistory(entry: PlanHistoryEntry) {
    const usaPro = entryUsesProFilters(entry);
    if (usaPro && !isPaid) {
      showAlert({
        variant: "warning",
        title: "Plan con filtros Pro",
        message:
          "Este plan se generó cuando tenías Pro. Podés verlo, pero no " +
          "podés regenerarlo sin Pro porque usa filtros bloqueados.",
      });
    }
    const seleccion: SeleccionConNombre[] = entry.filters.materias.map((m) => ({
      codigo: m.codigo,
      nombre: m.nombre,
      anual: m.anual ?? false,
      catedra_id: m.catedra_id,
      profesores: m.profesores,
      sede: m.sede ?? null,
      comision_codigo: m.comision_codigo ?? null,
      teorico_libre: m.teorico_libre ?? false,
      seminario_libre: m.seminario_libre ?? false,
    }));
    const dias = ALL_DIAS.filter(
      (d) => !entry.filters.dias_excluidos.includes(d),
    );
    const bache = entry.filters.max_bache_horas ?? null;
    const solo = entry.filters.solo_con_cupos ?? false;
    const rangos = {
      minDias: entry.filters.min_dias_semana ?? null,
      maxDias: entry.filters.max_dias_semana ?? null,
      minHoras: entry.filters.min_horas_dia ?? null,
      maxHoras: entry.filters.max_horas_dia ?? null,
    };
    setMaterias(seleccion);
    setDiasPermitidos(dias);
    setFranjas(entry.filters.franjas_excluidas);
    setSedesPermitidas(entry.filters.sedes_permitidas);
    setMaxBacheHoras(bache);
    setMinDiasSemana(rangos.minDias);
    setMaxDiasSemana(rangos.maxDias);
    setMinHorasDia(rangos.minHoras);
    setMaxHorasDia(rangos.maxHoras);
    setSoloCupos(solo);
    scrollOnNextResultRef.current = true;
    setResultado(entry.response);
    setPlanIdx(0);
    setError(false);
    setLastGeneratedSignature(
      JSON.stringify({
        materias: seleccion.map(toMateriaRequest),
        diasPermitidos: [...dias].sort(),
        franjas: entry.filters.franjas_excluidas,
        sedesPermitidas: [...entry.filters.sedes_permitidas].sort(),
        maxBacheHoras: bache,
        minDiasSemana: rangos.minDias,
        maxDiasSemana: rangos.maxDias,
        minHorasDia: rangos.minHoras,
        maxHorasDia: rangos.maxHoras,
        soloCupos: solo,
      }),
    );
    setLastGeneratedFilters(entry.filters);
    const q = encodeUrlState({
      m: seleccion.map((m) => ({
        c: m.codigo,
        ca: m.catedra_id,
        p: m.profesores,
        se: m.sede ?? null,
        co: m.comision_codigo ?? null,
        tl: m.teorico_libre || undefined,
        sl: m.seminario_libre || undefined,
      })),
      d: dias,
      f: entry.filters.franjas_excluidas,
      s: entry.filters.sedes_permitidas,
      b: bache,
      dmin: rangos.minDias ?? undefined,
      dmax: rangos.maxDias ?? undefined,
      hmin: rangos.minHoras ?? undefined,
      hmax: rangos.maxHoras ?? undefined,
      sc: solo || undefined,
    });
    const search = `?q=${q}`;
    sessionStorage.setItem("horarios:last-home-search", search);
    navigate(`/${search}`, { replace: true });
  }

  const planActual = resultado?.planes[planIdx] ?? null;
  const sinResultados = resultado && resultado.planes.length === 0;
  const materiasNombres = (codigos: number[]) =>
    codigos
      .map((c) => materias.find((m) => m.codigo === c)?.nombre ?? `#${c}`)
      .join(", ");

  const generarBarRef = useVisualViewportStick<HTMLDivElement>();

  const limpiarBtn = resultado !== null && (
    <Button
      size="lg"
      variant="outline"
      onClick={limpiarTodo}
      disabled={loading}
    >
      <BrushCleaning className="size-4" />
      Limpiar Todo
    </Button>
  );

  const generarBtn = (
    <Button
      size="lg"
      onClick={proFiltersBlocked ? () => openPaywall("filtros") : generar}
      disabled={
        loading ||
        materias.length === 0 ||
        diasPermitidos.length === 0 ||
        sinCambios
      }
      title={
        proFiltersBlocked
          ? "El plan actual usa filtros Pro. Hacete Pro para generarlo."
          : undefined
      }
      className={
        "flex-1 wide:flex-none " +
        (proFiltersBlocked
          ? "bg-[#EC990B] text-white hover:bg-[#EC990B]/90"
          : "bg-gradient-to-r from-primary to-[#C72A88] text-primary-foreground hover:opacity-90")
      }
    >
      {loading ? (
        <Loader2 className="size-4 animate-spin" />
      ) : proFiltersBlocked ? (
        <Gem className="size-4" />
      ) : (
        <Sparkles className="size-4" />
      )}
      {loading
        ? "Generando..."
        : proFiltersBlocked
          ? "Hacete Pro para generar"
          : "Generar planes"}
    </Button>
  );

  return (
    <div className="flex min-h-[100dvh] flex-col bg-background">
      <Seo
        title="Planify | Generá tus planes de cursada — Psicología UBA"
        description="Armá tu cuatrimestre en la Facultad de Psicología (UBA): combiná materias, cátedras y profesores sin superposiciones, filtrá por días, franjas y sedes, y generá todos los planes de cursada válidos."
        path="/"
      />
      <PagoErrorDialog state={pagoError} onClose={() => setPagoError(null)} />
      <PagoStatusDialog
        externalReference={pagoExternalRef}
        onClose={() => setPagoExternalRef(null)}
      />
      <Header />

      <main className="container flex flex-1 flex-col space-y-6 px-4 pb-24 pt-4 sm:px-6 wide:pb-8 wide:block">
        <div className="flex items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">
              Generador de planes de cursada
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Planificá tu cuatrimestre, combiná materias sin superposiciones
            </p>
          </div>
          <div className="hidden shrink-0 wide:block">
            <HistorialPopover onRestore={restoreFromHistory} />
          </div>
        </div>
        <div
          className={
            "flex flex-col gap-3 wide:grid wide:gap-6 wide:grid-cols-[1.1fr_1fr] wide:grid-rows-[1fr_auto] " +
            (resultado === null ? "flex-1" : "")
          }
        >
          <div className="flex shrink-0 flex-col gap-3 wide:flex-row">
            <div className="flex justify-end wide:hidden">
              <HistorialPopover onRestore={restoreFromHistory} />
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-3">
              {!isAuthenticated && <CarreraSelector />}
              <div className="relative flex-1">
                <Card className="flex flex-col wide:absolute wide:inset-0">
                  <CardHeader
                    className={materiasOpen ? undefined : "pb-6 wide:pb-4"}
                  >
                    <button
                      type="button"
                      onClick={() => setMateriasOpen((v) => !v)}
                      className="flex w-full items-center gap-2 text-left wide:pointer-events-none wide:cursor-default"
                    >
                      <ChevronDown
                        className={
                          "size-5 shrink-0 text-muted-foreground transition-transform wide:hidden " +
                          (materiasOpen ? "rotate-180" : "")
                        }
                      />
                      <BookOpen className="size-4 shrink-0 text-foreground wide:hidden" />
                      <CardTitle className="shrink-0">Materias</CardTitle>
                      <span className="flex min-w-0 items-center gap-1.5 text-xs font-medium text-muted-foreground">
                        {/* Punto "en vivo": el ping es una copia absolute que se
                            expande sobre el punto sólido. */}
                        <span className="relative flex size-2 shrink-0" aria-hidden>
                          <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-500 opacity-75 motion-reduce:hidden" />
                          <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
                        </span>
                        <span className="truncate">
                          {/* "Horarios" se cae en pantallas angostas: si no, la
                              fila no entra junto al contador de materias. */}
                          <span className="hidden sm:inline">Horarios </span>2do
                          cuatrimestre 2026
                        </span>
                      </span>
                      <span className="flex-1" />
                      {!materiasOpen && (
                        <span className="shrink-0 text-sm text-muted-foreground wide:hidden">
                          {materias.length}{" "}
                          {materias.length === 1 ? "materia" : "materias"}
                        </span>
                      )}
                    </button>
                  </CardHeader>
                  <CardContent
                    className={
                      (materiasOpen ? "flex" : "hidden wide:flex") +
                      " flex-col gap-4 wide:min-h-0 wide:flex-1"
                    }
                  >
                    <MateriaSelector
                      selected={materias}
                      onChange={setMaterias}
                    />
                  </CardContent>
                </Card>
              </div>
            </div>
          </div>

          <Card className="flex min-h-0 flex-col overflow-hidden wide:row-span-2 wide:sticky wide:top-6 wide:max-h-[calc(100dvh-13.75rem)]">
            <CardHeader className={filtrosOpen ? undefined : "pb-6 wide:pb-4"}>
              <div className="flex items-center justify-between gap-3">
                <button
                  type="button"
                  onClick={() => setFiltrosOpen((v) => !v)}
                  className="flex flex-1 items-center gap-2 text-left wide:cursor-default wide:pointer-events-none"
                >
                  <ChevronDown
                    className={
                      "size-5 shrink-0 text-muted-foreground transition-transform wide:hidden " +
                      (filtrosOpen ? "rotate-180" : "")
                    }
                  />
                  <Filter className="size-4 shrink-0 text-foreground wide:hidden" />
                  <CardTitle>Filtros</CardTitle>
                </button>
                {(diasPermitidos.length !== ALL_DIAS.length ||
                  franjas.length > 0 ||
                  sedesPermitidas.length > 0 ||
                  maxBacheHoras !== null ||
                  minDiasSemana !== null ||
                  maxDiasSemana !== null ||
                  minHorasDia !== null ||
                  maxHorasDia !== null ||
                  soloCupos) && (
                  <button
                    type="button"
                    onClick={() => {
                      setDiasPermitidos(ALL_DIAS);
                      setFranjas([]);
                      setSedesPermitidas([]);
                      setMaxBacheHoras(null);
                      setMinDiasSemana(null);
                      setMaxDiasSemana(null);
                      setMinHorasDia(null);
                      setMaxHorasDia(null);
                      setSoloCupos(false);
                    }}
                    className="text-sm font-medium leading-none text-primary hover:underline"
                  >
                    Restablecer todo
                  </button>
                )}
              </div>
            </CardHeader>
            <CardContent
              className={
                (filtrosOpen ? "flex" : "hidden wide:flex") +
                " min-h-0 flex-1 flex-col"
              }
            >
              <RestriccionesPanel
                diasPermitidos={diasPermitidos}
                onDiasPermitidosChange={setDiasPermitidos}
                franjas={franjas}
                onFranjasChange={setFranjas}
                sedesPermitidas={sedesPermitidas}
                onSedesChange={setSedesPermitidas}
                maxBacheHoras={maxBacheHoras}
                onMaxBacheHorasChange={setMaxBacheHoras}
                minDiasSemana={minDiasSemana}
                onMinDiasSemanaChange={setMinDiasSemana}
                maxDiasSemana={maxDiasSemana}
                onMaxDiasSemanaChange={setMaxDiasSemana}
                minHorasDia={minHorasDia}
                onMinHorasDiaChange={setMinHorasDia}
                maxHorasDia={maxHorasDia}
                onMaxHorasDiaChange={setMaxHorasDia}
                soloCupos={soloCupos}
                onSoloCuposChange={setSoloCupos}
                isPaid={isPaid}
                isLoading={subLoading}
                onUpgrade={() => openPaywall("filtros")}
              />
            </CardContent>
          </Card>

          <div
            className={
              "hidden gap-3 wide:flex " +
              (resultado === null ? "mt-auto wide:mt-0" : "")
            }
          >
            <div className="flex flex-1 flex-col items-stretch gap-3 wide:flex-row wide:items-center wide:justify-between wide:gap-4">
              <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                {materias.length === 0 ? (
                  <>
                    <AlertCircle className="size-4 shrink-0" />
                    Agregá al menos una materia
                  </>
                ) : (
                  `Listo para generar planes con ${materias.length} ${materias.length === 1 ? "materia" : "materias"}.`
                )}
              </p>
              <div className="flex flex-col items-stretch gap-3 wide:flex-row wide:items-center wide:gap-2">
                {limpiarBtn}
                {generarBtn}
              </div>
            </div>
          </div>
        </div>

        {error && (
          <div className="rounded-2xl border border-destructive/30 bg-destructive/5 p-4">
            <ErrorState
              title="No pudimos generar los planes"
              description="Revisá tu conexión y volvé a intentar."
              onRetry={generar}
              retrying={loading}
              className="py-2"
            />
          </div>
        )}

        {sinResultados && (
          <div className="rounded-2xl border border-amber-300 bg-amber-50 p-5 text-sm">
            <p className="font-medium text-amber-900">
              No se encontraron planes válidos
            </p>
            {resultado!.materias_sin_opciones.length > 0 ? (
              <p className="mt-1 text-amber-800">
                Las restricciones no dejan ninguna opción para:{" "}
                <span className="font-medium">
                  {materiasNombres(resultado!.materias_sin_opciones)}
                </span>
                . Probá cambiar los filtros de días, franjas, cátedra o
                profesores.
              </p>
            ) : (
              <p className="mt-1 text-amber-800">
                Todas las combinaciones se solapan entre sí. Probá quitar alguna
                materia o cambiar filtros.
              </p>
            )}
          </div>
        )}

        {loading && (
          <Card
            ref={calendarioRef}
            className="-mx-4 rounded-none wide:mx-0 wide:rounded-2xl"
          >
            <CardHeader>
              <CardTitle>Calendario</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                Generando planes…
              </p>
            </CardHeader>
            <CardContent>
              <CalendarioPlanSkeleton compacto={calendarioCompacto} />
            </CardContent>
          </Card>
        )}

        {!loading && resultado && resultado.planes.length > 0 && (
          <Card
            ref={calendarioRef}
            className="-mx-4 rounded-none wide:mx-0 wide:rounded-2xl"
          >
            <CardHeader className="flex-col items-stretch gap-3 wide:flex-row wide:items-center wide:justify-between">
              <div>
                <CardTitle>Calendario</CardTitle>
                <p className="mt-1 text-xs text-muted-foreground">
                  {resultado.planes.length} plan
                  {resultado.planes.length === 1 ? "" : "es"} sin solapamientos
                </p>
              </div>
              <div className="order-3 flex w-full justify-center wide:order-none wide:flex-1">
                <PlanNavigator
                  index={planIdx}
                  total={resultado.planes.length}
                  displayTotal={
                    !isPaid && resultado.planes.length >= FREE_MAX_PLANES
                      ? PRO_MAX_PLANES
                      : undefined
                  }
                  freemiumLocked={
                    !isPaid && resultado.planes.length >= FREE_MAX_PLANES
                  }
                  onUpgrade={() => openPaywall("planes-limit")}
                  onChange={setPlanIdx}
                />
              </div>
              <div className="order-2 flex w-full items-center justify-between gap-3 wide:order-none wide:w-auto wide:justify-start">
                <div className="flex items-center gap-2">
                  <Label
                    htmlFor="compacto-switch"
                    className="text-xs text-muted-foreground"
                  >
                    Compacto
                  </Label>
                  <Switch
                    id="compacto-switch"
                    checked={calendarioCompacto}
                    onCheckedChange={setCalendarioCompacto}
                  />
                </div>
                {planActual && lastGeneratedFilters && (
                  <SaveFavoriteButton
                    plan={planActual}
                    filters={lastGeneratedFilters}
                    isPaid={isPaid}
                    onLockedClick={() => openPaywall("favoritos")}
                  />
                )}
              </div>
            </CardHeader>
            <CardContent>
              <CalendarioPlan
                plan={planActual}
                compacto={calendarioCompacto}
                // Las del último "Generar", no las del panel: el calendario
                // tiene que coincidir con el plan que se está mostrando.
                franjasBloqueadas={lastGeneratedFilters?.franjas_excluidas}
              />
            </CardContent>
          </Card>
        )}
      </main>

      <div
        ref={generarBarRef}
        className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card/95 backdrop-blur wide:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <div className="container flex items-center gap-2 px-4 pt-3 pb-5">
          {limpiarBtn}
          {generarBtn}
        </div>
      </div>
    </div>
  );
}
