import { useEffect, useState } from "react";

// Default: el breakpoint `wide` (821px) de tailwind.config.ts.
export function useIsWide(minWidth = 821): boolean {
  const [isWide, setIsWide] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(`(min-width: ${minWidth}px)`);
    const update = () => setIsWide(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [minWidth]);
  return isWide;
}
