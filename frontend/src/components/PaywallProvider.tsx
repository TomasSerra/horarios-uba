import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/useAuth";
import { useSubscription } from "@/lib/useSubscription";
import { QRCodeSVG } from "qrcode.react";
import {
  Check,
  CheckCircle2,
  Gem,
  Loader2,
  LogIn,
  ShieldCheck,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import mpIcon from "@/assets/mp-icon.png";
import { api, API_BASE } from "@/lib/api";
import { useAlert } from "@/lib/alert";
import { markProActive } from "@/lib/useMe";
import { PaywallContext, type PaywallReason } from "@/lib/paywall";
import { cn } from "@/lib/utils";

// Precio configurable desde Vercel (VITE_SUBSCRIPTION_PRICE_ARS). El precio
// real que cobra MP lo define el backend; mantener en sync con ese env.
const SUBSCRIPTION_PRICE_ARS =
  Number(import.meta.env.VITE_SUBSCRIPTION_PRICE_ARS) || 2490;
const SUBSCRIPTION_MONTHS = 3;

export const FREE_MAX_PLANES = 15;
export const PRO_MAX_PLANES = 100;
export const FREE_MAX_REVIEWS = 5;

// Filas de la comparación gratis vs pro. Reflejan lo que
// `_request_uses_filters` (backend/api/main.py) gatea como Pro: días
// excluidos + cupos son gratis; franjas/sedes/bache + cátedra/profes
// + favoritos son Pro.
// `free`/`pro` para la tabla: boolean → ✓/✗, string → valor literal.
// `cardFreeText`/`cardProText` son overrides para el render de cards
// (cuando el texto difiere por columna, e.g. "Hasta 15..." vs "Hasta 100...").
const COMPARISON_ROWS: {
  label: string;
  free: boolean | string;
  pro: boolean | string;
  cardFreeText?: string;
  cardProText?: string;
}[] = [
  {
    label: "Generador de planes",
    free: true,
    pro: true,
  },
  {
    label: "Planes por generación",
    free: `Hasta ${FREE_MAX_PLANES}`,
    pro: `Hasta ${PRO_MAX_PLANES}`,
    cardFreeText: `Hasta ${FREE_MAX_PLANES} planes por generación`,
    cardProText: `Hasta ${PRO_MAX_PLANES} planes por generación`,
  },
  {
    label: "Filtros básicos: días y cupos disponibles",
    free: true,
    pro: true,
  },
  {
    label: "Filtros avanzados: franjas horarias, sedes y bache máximo",
    free: false,
    pro: true,
  },
  {
    label: "Elegir cátedra fija o profesores",
    free: false,
    pro: true,
  },
  {
    label: "Guardar planes favoritos",
    free: false,
    pro: true,
  },
  {
    label: "Reseñas visibles por cátedra",
    free: `Primeras ${FREE_MAX_REVIEWS}`,
    pro: "Todas",
    cardFreeText: `Primeras ${FREE_MAX_REVIEWS} reseñas por cátedra`,
    cardProText: "Todas las reseñas por cátedra",
  },
];

const PAYWALL_COPY: Record<
  PaywallReason,
  { title: string; description: string }
> = {
  catedra: {
    title: "Elegí tu cátedra con Pro",
    description: "Fijar la cátedra de una materia es Pro.",
  },
  profesores: {
    title: "Elegí tus profesores con Pro",
    description: "Filtrar por profesores específicos es Pro.",
  },
  filtros: {
    title: "Más filtros con Pro",
    description:
      "Filtrar por franjas horarias, sedes, bache máximo y límites de días y horas de cursada es Pro.",
  },
  favoritos: {
    title: "Guardá tus planes con Pro",
    description: "Guardar planes favoritos es Pro.",
  },
  "planes-limit": {
    title: "Más planes con Pro",
    description: `Con gratis generás hasta ${FREE_MAX_PLANES} planes por generación.`,
  },
  reviews: {
    title: "Leé todas las reseñas con Pro",
    description: `Con gratis ves las primeras ${FREE_MAX_REVIEWS} reseñas de cada cátedra.`,
  },
  general: {
    title: "Armá tu cuatri sin límites",
    description: "Pasate a Pro por menos de lo que sale un café.",
  },
};

const formattedPrice = new Intl.NumberFormat("es-AR").format(
  SUBSCRIPTION_PRICE_ARS,
);

// Mismo breakpoint que el `md:` de Tailwind. Reactivo porque decide qué
// componente renderizar (Dialog de desktop vs sheet custom de mobile).
function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState(
    () => window.matchMedia("(min-width: 768px)").matches,
  );
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    const update = () => setIsDesktop(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return isDesktop;
}

function PaywallDialog({
  open,
  reason,
  onOpenChange,
}: {
  open: boolean;
  reason: PaywallReason | null;
  onOpenChange: (v: boolean) => void;
}) {
  const { getAccessTokenSilently, isAuthenticated, openLogin } = useAuth();
  const { isPaid, isLoading: subLoading } = useSubscription();
  const showAlert = useAlert();
  const [showPayment, setShowPayment] = useState(false);
  const [mobileRedirectLoading, setMobileRedirectLoading] = useState(false);

  useEffect(() => {
    if (!open) {
      setShowPayment(false);
      setMobileRedirectLoading(false);
    }
  }, [open]);

  // Estables a propósito: PaymentMethodDialog tiene onPaid en las deps del
  // efecto que acredita el pago, y una arrow inline lo re-dispararía en cada
  // render.
  const cerrarPago = useCallback(() => setShowPayment(false), []);
  const handlePaid = useCallback(() => {
    setShowPayment(false);
    setTimeout(() => onOpenChange(false), 1500);
  }, [onOpenChange]);

  async function handleHaceteProClick() {
    if (!isAuthenticated) {
      openLogin("signin");
      return;
    }
    if (isPaid) return;

    // En mobile saltamos el modal de método de pago (no tiene QR útil) y
    // mandamos directo al checkout de MP. En desktop abrimos el modal con
    // QR + botón web.
    const isDesktop = window.matchMedia("(min-width: 768px)").matches;
    if (isDesktop) {
      setShowPayment(true);
      return;
    }

    setMobileRedirectLoading(true);
    try {
      const token = await getAccessTokenSilently();
      const { init_point } = await api.postCheckout(token, "redirect");
      window.location.href = init_point;
    } catch (e) {
      setMobileRedirectLoading(false);
      showAlert({
        variant: "error",
        title: "No se pudo iniciar el pago",
        message: (e as Error).message,
      });
    }
  }

  const { title, description } = PAYWALL_COPY[reason ?? "general"];
  const isDesktop = useIsDesktop();

  const ctaButton = !isAuthenticated ? (
    <Button
      size="lg"
      className="w-full bg-[#EC990B] text-white hover:bg-[#EC990B]/90"
      onClick={() => openLogin("signin")}
    >
      <LogIn className="size-4" />
      Iniciar sesión
    </Button>
  ) : subLoading ? (
    <div className="flex items-center justify-center py-3">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div>
  ) : isPaid ? (
    <div className="flex items-center justify-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700">
      <CheckCircle2 className="size-4" />
      Ya tenés Pro activo
    </div>
  ) : (
    <Button
      size="lg"
      className="mx-auto w-full bg-[#EC990B] text-white hover:bg-[#EC990B]/90 md:max-w-xs"
      onClick={handleHaceteProClick}
      disabled={mobileRedirectLoading}
    >
      {mobileRedirectLoading ? (
        <Loader2 className="size-4 animate-spin" />
      ) : (
        <img src={mpIcon} alt="" className="h-4 w-auto" />
      )}
      <span className="md:hidden">Pagar con Mercado Pago</span>
      <span className="hidden md:inline">Hacete Pro</span>
    </Button>
  );

  return (
    <>
      {isDesktop ? (
        <Dialog open={open} onOpenChange={onOpenChange}>
          <DialogContent className="h-auto max-h-[90vh] w-[calc(100vw-2rem)] max-w-2xl overflow-y-auto rounded-2xl border">
            <DialogHeader className="text-center sm:text-center">
              <DialogTitle className="flex items-center justify-center gap-2 text-center">
                <Gem className="size-5 text-[#EC990B]" />
                {title}
              </DialogTitle>
              <DialogDescription className="text-center">
                {description}
              </DialogDescription>
            </DialogHeader>

            <div className="flex flex-col gap-4">
              <ComparisonTable />
              {ctaButton}
            </div>

            {isAuthenticated && (
              <p className="flex items-center justify-center gap-1.5 text-center text-xs text-muted-foreground">
                <ShieldCheck className="size-4 shrink-0 text-emerald-600" />
                Pago único. No es una suscripción automática.
              </p>
            )}
          </DialogContent>
        </Dialog>
      ) : (
        <PaywallMobileSheet
          open={open}
          onOpenChange={onOpenChange}
          title={title}
          description={description}
          showPolicy={isAuthenticated}
          ctaButton={ctaButton}
        />
      )}

      <PaymentMethodDialog
        open={open && showPayment}
        onClose={cerrarPago}
        onPaid={handlePaid}
      />
    </>
  );
}

// Sheet custom de mobile: panel full-screen con el CTA SIEMPRE visible.
// Usamos 100dvh (dynamic viewport height) en vez de 100vh para medir el
// viewport visible real — así la chrome del navegador no tapa el footer — y
// fijamos el botón en un footer shrink-0; solo el cuerpo (la tabla) scrollea.
function PaywallMobileSheet({
  open,
  onOpenChange,
  title,
  description,
  showPolicy,
  ctaButton,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  showPolicy: boolean;
  ctaButton: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onOpenChange]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true">
      <div
        className="absolute inset-0 bg-black/50"
        onClick={() => onOpenChange(false)}
      />
      <div className="absolute inset-0 flex h-[100dvh] flex-col bg-white">
        <div className="relative shrink-0 border-b px-4 pb-3 pt-4 text-center">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="absolute right-3 top-3 rounded-full p-1 text-muted-foreground hover:bg-muted"
            aria-label="Cerrar"
          >
            <X className="size-5" />
          </button>
          <h2 className="flex items-center justify-center gap-2 text-lg font-semibold">
            <Gem className="size-5 text-[#EC990B]" />
            {title}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          <ComparisonTable />
        </div>

        <div className="shrink-0 border-t px-4 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3">
          {ctaButton}
          {showPolicy && (
            <p className="mt-2 flex items-center justify-center gap-1.5 text-center text-xs text-muted-foreground">
              <ShieldCheck className="size-4 shrink-0 text-emerald-600" />
              Pago único. No es una suscripción automática.
            </p>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

// Layout alternativo de desktop (dos cards lado a lado en vez de tabla).
// Lo dejamos guardado por si querés volver a esta presentación: en el
// PaywallDialog cambiá el render del cuerpo a `<PaywallCardsLayout ... />`.
export function PaywallCardsLayout({
  ctaButton,
  isPaid,
}: {
  ctaButton: ReactNode;
  isPaid: boolean;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <PlanCard kind="free" isPaid={isPaid} />
      <PlanCard kind="pro" isPaid={isPaid} cta={ctaButton} />
    </div>
  );
}

function PlanCard({
  kind,
  isPaid,
  cta,
}: {
  kind: "free" | "pro";
  isPaid: boolean;
  cta?: ReactNode;
}) {
  const isPro = kind === "pro";
  const showRecommended = isPro && !isPaid;

  return (
    <div
      className={cn(
        "relative flex flex-col gap-3 rounded-2xl border p-4",
        isPro ? "border-[#EC990B]/40 bg-[#EC990B]/5" : "border-border bg-white",
      )}
    >
      {showRecommended && (
        <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-[#EC990B] px-3 py-0.5 text-xs font-semibold text-white shadow-sm">
          Recomendado
        </span>
      )}
      <div className="flex flex-col gap-1">
        <h3 className="flex items-center gap-1.5 text-base font-semibold">
          {isPro && <Gem className="size-4 text-[#EC990B]" />}
          {isPro ? "Pro" : "Gratis"}
        </h3>
        {isPro ? (
          <>
            <p className="text-2xl font-bold">
              ${formattedPrice}
              <span className="ml-1 text-sm font-normal text-muted-foreground">
                / {SUBSCRIPTION_MONTHS} meses
              </span>
            </p>
            <p className="text-xs text-muted-foreground">Pago único</p>
          </>
        ) : (
          <>
            <p className="text-2xl font-bold">$0</p>
            <p className="text-xs text-muted-foreground">
              {isPaid ? "Plan anterior" : "Lo que tenés ahora"}
            </p>
          </>
        )}
      </div>

      <ul className="flex flex-col gap-2">
        {COMPARISON_ROWS.map((row) => {
          const text = isPro
            ? (row.cardProText ?? row.label)
            : (row.cardFreeText ?? row.label);
          const enabled = isPro ? row.pro !== false : row.free !== false;
          return (
            <li
              key={text + (isPro ? ":pro" : ":free")}
              className="flex items-start gap-2 text-sm"
            >
              {enabled ? (
                <Check
                  className={cn(
                    "mt-0.5 size-4 shrink-0",
                    isPro ? "text-[#EC990B]" : "text-emerald-600",
                  )}
                  strokeWidth={2.5}
                />
              ) : (
                <X
                  className="mt-0.5 size-4 shrink-0 text-muted-foreground/60"
                  strokeWidth={2.5}
                />
              )}
              <span
                className={cn(
                  "leading-snug",
                  enabled ? "" : "text-muted-foreground/70",
                )}
              >
                {text}
              </span>
            </li>
          );
        })}
      </ul>

      {isPro ? (
        cta
      ) : (
        <div className="rounded-md border border-dashed px-3 py-2 text-center text-sm font-medium text-muted-foreground">
          {isPaid ? "Plan anterior" : "Tu plan actual"}
        </div>
      )}
    </div>
  );
}

function ComparisonCell({
  value,
  isPro,
}: {
  value: boolean | string;
  isPro: boolean;
}) {
  if (typeof value === "string") {
    return (
      <span
        className={cn(
          "text-sm font-semibold",
          isPro ? "text-[#EC990B]" : "text-muted-foreground font-normal",
        )}
      >
        {value}
      </span>
    );
  }
  return value ? (
    <Check
      className={cn(
        "mx-auto size-5",
        isPro ? "text-[#EC990B]" : "text-emerald-600",
      )}
      strokeWidth={2.5}
    />
  ) : (
    <X className="mx-auto size-5 text-red-500" strokeWidth={2.5} />
  );
}

function ComparisonTable() {
  return (
    <div className="relative mt-4 rounded-xl border sm:mt-2">
      <table className="w-full border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            <th className="border-b px-3 py-3 sm:pt-5 text-left font-medium text-muted-foreground" />
            <th className="border-b px-2 py-3 sm:pt-5 text-center align-top w-[20%]">
              <div className="font-semibold">Gratis</div>
              <div className="text-sm">$0</div>
            </th>
            <th className="relative w-[30%] rounded-t-xl border-x-2 border-t-2 border-[#EC990B] bg-[#EC990B]/10 px-2 py-3 sm:pt-5 text-center align-top">
              <span className="pointer-events-none absolute left-1/2 top-[-4px] hidden -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full bg-[#EC990B] px-3 py-2 text-sm font-semibold text-white sm:block">
                Oferta lanzamiento
              </span>
              <div className="flex items-center justify-center gap-1 font-semibold text-[#EC990B]">
                <Gem className="size-3.5" />
                Pro
              </div>
              <div>
                <span className="text-sm font-bold text-foreground">
                  ${formattedPrice}
                </span>
                <span className="ml-1 block text-xs font-normal text-muted-foreground md:inline">
                  / {SUBSCRIPTION_MONTHS} meses
                </span>
              </div>
            </th>
          </tr>
        </thead>
        <tbody>
          {COMPARISON_ROWS.map((row, idx) => {
            const isLast = idx === COMPARISON_ROWS.length - 1;
            return (
              <tr key={row.label}>
                <td
                  className={cn(
                    "px-3 py-3 leading-snug",
                    !isLast && "border-b",
                  )}
                >
                  {row.label}
                </td>
                <td
                  className={cn("px-2 py-3 text-center", !isLast && "border-b")}
                >
                  <ComparisonCell value={row.free} isPro={false} />
                </td>
                <td
                  className={cn(
                    "border-x-2 border-[#EC990B] bg-[#EC990B]/5 px-2 py-3 text-center",
                    isLast && "rounded-b-xl border-b-2",
                  )}
                >
                  <ComparisonCell value={row.pro} isPro={true} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PaymentMethodDialog({
  open,
  onClose,
  onPaid,
}: {
  open: boolean;
  onClose: () => void;
  onPaid: () => void;
}) {
  const { getAccessTokenSilently, openLogin } = useAuth();
  const queryClient = useQueryClient();
  const showAlert = useAlert();
  const [redirectInitPoint, setRedirectInitPoint] = useState<string | null>(
    null,
  );
  const [qrExternalReference, setQrExternalReference] = useState<string | null>(
    null,
  );
  const [qrError, setQrError] = useState<string | null>(null);
  const [redirectLoading, setRedirectLoading] = useState(false);
  const qrInFlightRef = useRef(false);
  const redirectStartedAtRef = useRef<number | null>(null);
  const safetyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!open) {
      setRedirectInitPoint(null);
      setQrExternalReference(null);
      setQrError(null);
      setRedirectLoading(false);
      qrInFlightRef.current = false;
      redirectStartedAtRef.current = null;
      if (safetyTimeoutRef.current !== null) {
        clearTimeout(safetyTimeoutRef.current);
        safetyTimeoutRef.current = null;
      }
    }
  }, [open]);

  // El in-flight guard va en un ref (no state): si fuera state, setear
  // qrLoading=true re-dispararía este mismo effect, lo que correría el cleanup
  // y marcaría la promesa como cancelada antes de que vuelva con la respuesta.
  useEffect(() => {
    if (!open) return;
    if (qrExternalReference || qrInFlightRef.current) return;
    const isDesktop = window.matchMedia("(min-width: 768px)").matches;
    if (!isDesktop) return;

    let cancelled = false;
    qrInFlightRef.current = true;
    setQrError(null);
    (async () => {
      try {
        const token = await getAccessTokenSilently();
        const { external_reference } = await api.postCheckout(token, "qr");
        if (cancelled) return;
        setQrExternalReference(external_reference);
      } catch (e) {
        if (!cancelled) setQrError((e as Error).message);
      } finally {
        qrInFlightRef.current = false;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, qrExternalReference, getAccessTokenSilently]);

  const { data: qrPagoStatus } = useQuery({
    queryKey: ["pago-status", qrExternalReference],
    queryFn: () => {
      if (!qrExternalReference) throw new Error("Falta external_reference");
      return api.getPagoStatus(qrExternalReference);
    },
    enabled: open && !!qrExternalReference,
    refetchInterval: (q) =>
      q.state.data?.status === "approved" ? false : 5000,
  });

  // Misma guarda que en PagoStatusDialog (Home.tsx): una vez por pago, porque
  // el write al cache de /me re-renderiza al padre y sin esto el efecto se
  // re-dispararía en loop.
  const acreditadoRef = useRef<string | null>(null);
  useEffect(() => {
    if (qrPagoStatus?.status !== "approved") return;
    if (acreditadoRef.current !== qrExternalReference) {
      acreditadoRef.current = qrExternalReference;
      markProActive(queryClient);
    }
    const t = setTimeout(onPaid, 1500);
    return () => clearTimeout(t);
  }, [qrPagoStatus?.status, qrExternalReference, queryClient, onPaid]);

  // Si el user va a MP y vuelve sin pagar, el botón puede quedar en loading.
  // visibilitychange + timeout de seguridad resetean cuando la tab vuelve.
  useEffect(() => {
    if (!redirectLoading) {
      redirectStartedAtRef.current = null;
      if (safetyTimeoutRef.current !== null) {
        clearTimeout(safetyTimeoutRef.current);
        safetyTimeoutRef.current = null;
      }
      return;
    }
    redirectStartedAtRef.current = Date.now();
    safetyTimeoutRef.current = setTimeout(
      () => setRedirectLoading(false),
      10_000,
    );
    function onVisibility() {
      if (document.visibilityState !== "visible") return;
      const started = redirectStartedAtRef.current;
      if (started === null) return;
      if (Date.now() - started < 800) return;
      setRedirectLoading(false);
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      if (safetyTimeoutRef.current !== null) {
        clearTimeout(safetyTimeoutRef.current);
        safetyTimeoutRef.current = null;
      }
    };
  }, [redirectLoading]);

  async function pagar() {
    setRedirectLoading(true);
    try {
      let ip = redirectInitPoint;
      if (!ip) {
        let token: string;
        try {
          token = await getAccessTokenSilently();
        } catch {
          openLogin("signin");
          return;
        }
        const { init_point } = await api.postCheckout(token, "redirect");
        ip = init_point;
        setRedirectInitPoint(ip);
      }
      window.location.href = ip;
    } catch (e) {
      showAlert({
        variant: "error",
        title: "No se pudo iniciar el pago",
        message: (e as Error).message,
      });
    } finally {
      setRedirectLoading(false);
    }
  }

  const approved = qrPagoStatus?.status === "approved";

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Gem className="size-5 text-[#EC990B]" />
            Pagá desde tu celular
          </DialogTitle>
          <DialogDescription>
            Escaneá con la <strong>cámara del celular</strong>, no con la app de
            Mercado Pago. Serás redirigido a la app de Mercado Pago.
          </DialogDescription>
        </DialogHeader>

        {approved ? (
          <div className="flex flex-col items-center gap-2 py-4 text-center">
            <CheckCircle2
              className="size-12 text-emerald-600"
              strokeWidth={1.5}
            />
            <p className="text-sm font-medium">¡Pago acreditado! Ya sos Pro</p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="hidden flex-col items-center gap-2 md:flex">
              {qrError ? (
                <p className="px-2 text-center text-xs text-destructive">
                  No se pudo generar el QR: {qrError}
                </p>
              ) : qrExternalReference ? (
                <div className="rounded-lg border bg-white p-3">
                  <QRCodeSVG
                    value={`${API_BASE}/pagos/qr/${qrExternalReference}`}
                    size={160}
                  />
                </div>
              ) : (
                <div className="flex h-[160px] w-[160px] items-center justify-center rounded-lg border bg-muted/30">
                  <Loader2 className="size-6 animate-spin text-muted-foreground" />
                </div>
              )}
            </div>

            <div className="flex flex-col items-center gap-0.5">
              <p className="text-3xl font-bold">${formattedPrice}</p>
              <p className="text-sm text-muted-foreground">
                {SUBSCRIPTION_MONTHS} meses · Pago único
              </p>
            </div>

            <div className="hidden items-center gap-3 md:flex">
              <div className="h-px flex-1 bg-border" />
              <span className="text-xs uppercase tracking-wide text-muted-foreground">
                o
              </span>
              <div className="h-px flex-1 bg-border" />
            </div>

            <Button
              size="lg"
              className="w-full bg-[#EC990B] text-white hover:bg-[#EC990B]/90"
              onClick={pagar}
              disabled={redirectLoading}
            >
              {redirectLoading ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <img src={mpIcon} alt="" className="h-4 w-auto" />
              )}
              Pagar desde la web
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function PaywallProvider({ children }: { children: ReactNode }) {
  const [reason, setReason] = useState<PaywallReason | null>(null);
  const open = useCallback(
    (r: PaywallReason = "general") => setReason(r),
    [],
  );
  const handleOpenChange = useCallback((v: boolean) => {
    if (!v) setReason(null);
  }, []);

  return (
    <PaywallContext.Provider value={open}>
      {children}
      <PaywallDialog
        open={reason !== null}
        reason={reason}
        onOpenChange={handleOpenChange}
      />
    </PaywallContext.Provider>
  );
}
