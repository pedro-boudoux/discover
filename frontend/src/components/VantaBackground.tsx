import { useEffect, useRef } from "react";
import * as THREE from "three";

// Side-effect import registers window.VANTA.CLOUDS — more reliable than
// relying on Vite's CJS/ESM interop for UMD dist files.
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import "vanta/dist/vanta.clouds.min";

declare global {
  interface Window {
    THREE: typeof THREE;
    VANTA: { CLOUDS: (opts: Record<string, unknown>) => { destroy(): void } };
  }
}

type VantaEffect = { destroy(): void };

export function VantaBackground() {
  const containerRef = useRef<HTMLDivElement>(null);
  const effectRef = useRef<VantaEffect | null>(null);

  useEffect(() => {
    if (!containerRef.current || effectRef.current) return;

    effectRef.current = window.VANTA.CLOUDS({
      el: containerRef.current,
      THREE,               // must be passed explicitly — Vanta captures window.THREE at module load time, before React runs
      speed: 0.75,
      scale: 3,
    });

    return () => {
      effectRef.current?.destroy();
      effectRef.current = null;
    };
  }, []);

  return <div ref={containerRef} className="absolute inset-0 w-full h-full" />;
}
