import { useLayoutEffect, useRef, useState } from "react";

/**
 * Clampea un contenedor a `rowsVisible` filas completas + media fila más, para
 * que se lea que hay contenido abajo. La altura se mide en runtime porque los
 * hijos wrapean según el ancho: no hay un count fijo de columnas.
 *
 * Devuelve `collapsedHeight === null` cuando no hay nada que clampear (el
 * contenido entra en las filas visibles).
 */
export function useClampRows(rowsVisible: number, deps: unknown[] = []) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [collapsedHeight, setCollapsedHeight] = useState<number | null>(null);
  // Índice del primer hijo de la fila cortada: de ahí en adelante están
  // recortados y no se leen enteros.
  const [cutFromIndex, setCutFromIndex] = useState<number | null>(null);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const reset = () => {
      setCollapsedHeight(null);
      setCutFromIndex(null);
    };
    const measure = () => {
      const hijos = Array.from(el.children) as HTMLElement[];
      if (hijos.length === 0) return reset();
      // Posiciones relativas al contenedor (getBoundingClientRect, no offsetTop:
      // offsetTop es relativo al offsetParent posicionado, no a este div).
      // Redondeamos el top para que el subpixel no invente filas de más.
      const cTop = el.getBoundingClientRect().top;
      const rects = hijos.map((c) => {
        const r = c.getBoundingClientRect();
        return { top: Math.round(r.top - cTop), bottom: r.bottom - cTop };
      });
      const tops = Array.from(new Set(rects.map((r) => r.top))).sort(
        (a, b) => a - b
      );
      if (tops.length <= rowsVisible) return reset();
      // Cortamos a mitad de la primera fila oculta. tops[rowsVisible] ya incluye
      // el gap, así que alcanza con sumarle media altura de esa fila.
      const filaCortada = rects.filter((r) => r.top === tops[rowsVisible]);
      const altoFilaCortada =
        Math.max(...filaCortada.map((r) => r.bottom)) - tops[rowsVisible];
      setCollapsedHeight(tops[rowsVisible] + altoFilaCortada / 2);
      setCutFromIndex(rects.findIndex((r) => r.top === tops[rowsVisible]));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowsVisible, ...deps]);

  return {
    containerRef,
    expanded,
    setExpanded,
    collapsedHeight,
    cutFromIndex,
    clamp: collapsedHeight != null && !expanded,
  };
}
