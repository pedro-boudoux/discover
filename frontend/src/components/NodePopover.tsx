import { useState } from "react";
import type { ExpansionMethod, ExpansionParams } from "../types";
import { DEFAULT_EXPANSION } from "../types";

type Props = {
  nodeLabel: string;
  isSeed: boolean;
  loading: boolean;
  onExpand: (params: ExpansionParams) => void;
  onDelete: () => void;
  onClose: () => void;
  initial?: ExpansionParams;
};

export function NodePopover({
  nodeLabel,
  isSeed,
  loading,
  onExpand,
  onDelete,
  onClose,
  initial,
}: Props) {
  const [params, setParams] = useState<ExpansionParams>(initial ?? DEFAULT_EXPANSION);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  function update<K extends keyof ExpansionParams>(key: K, value: ExpansionParams[K]) {
    setParams((p) => ({ ...p, [key]: value }));
  }

  return (
    <div className="relative w-[300px] overflow-hidden rounded-[15px] shadow-[0px_1px_4.1px_0px_rgba(0,0,0,0.25)]">
      <div aria-hidden className="absolute inset-0 backdrop-blur-[4px] bg-white/[0.88] rounded-[15px] pointer-events-none" />
      <div aria-hidden className="absolute inset-0 pointer-events-none rounded-[15px] shadow-[inset_0px_4px_4px_0px_rgba(255,255,255,0.25)]" />
      <div className="relative p-4 text-sm text-[#3a3a3a]">
        <div className="flex items-start justify-between gap-2 mb-3">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-widest text-[#8a8a8a] font-medium">
              Expand from
            </div>
            <div className="truncate font-semibold text-[#1a1a1a]">{nodeLabel}</div>
          </div>
          <button
            onClick={onClose}
            className="text-[#8a8a8a] hover:text-[#3a3a3a] px-1 leading-none transition-colors"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <Label>Method</Label>
        <div className="grid grid-cols-3 gap-1 mb-3">
          {(["recommendations", "linear", "tree"] as ExpansionMethod[]).map((m) => (
            <button
              key={m}
              onClick={() => update("method", m)}
              className={[
                "px-2 py-1.5 rounded-md text-xs border transition",
                params.method === m
                  ? "border-blue-400 text-blue-600 bg-blue-50/80 font-medium"
                  : "border-[#d0d0d0] text-[#8a8a8a] hover:text-[#3a3a3a] hover:border-[#a0a0a0]",
              ].join(" ")}
            >
              {m === "recommendations" ? "MMR" : m === "linear" ? "Linear" : "Tree"}
            </button>
          ))}
        </div>

        <SliderRow
          label="Number of songs"
          value={params.k}
          min={1}
          max={20}
          step={1}
          suffix={String(params.k)}
          onChange={(v) => update("k", v)}
        />

        {params.method === "recommendations" && (
          <SliderRow
            label="Diversity (λ)"
            value={params.lambda}
            min={0}
            max={1}
            step={0.05}
            suffix={params.lambda.toFixed(2)}
            onChange={(v) => update("lambda", v)}
            hint={
              params.lambda > 0.7
                ? "close to seed"
                : params.lambda < 0.4
                  ? "very diverse"
                  : "balanced"
            }
          />
        )}

        {params.method === "tree" && (
          <SliderRow
            label="Max depth"
            value={params.maxDepth}
            min={1}
            max={5}
            step={1}
            suffix={String(params.maxDepth)}
            onChange={(v) => update("maxDepth", v)}
          />
        )}

        {(params.method === "linear" || params.method === "tree") && (
          <label className="flex items-center gap-2 mt-3 text-xs cursor-pointer select-none">
            <input
              type="checkbox"
              checked={params.niche}
              onChange={(e) => update("niche", e.target.checked)}
              className="accent-blue-500"
            />
            <span className="text-[#8a8a8a]">Niche mode (favor low listener counts)</span>
          </label>
        )}

        <label className="flex items-center gap-2 mt-3 text-xs cursor-pointer select-none">
          <input
            type="checkbox"
            checked={params.allowDuplicates}
            onChange={(e) => update("allowDuplicates", e.target.checked)}
            className="accent-blue-500"
          />
          <span className="text-[#8a8a8a]">Allow songs already in graph</span>
        </label>

        <button
          disabled={loading}
          onClick={() => onExpand(params)}
          className="mt-4 w-full bg-blue-500 text-white font-semibold rounded-xl py-2 text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-blue-600 transition-colors"
        >
          {loading ? "Expanding…" : "Expand"}
        </button>

        <div className="mt-3 pt-3 border-t border-[#e0e0e0]/60">
          <button
            disabled={loading}
            onClick={() => {
              if (confirmingDelete) onDelete();
              else setConfirmingDelete(true);
            }}
            className={[
              "w-full rounded-md py-2 text-xs font-medium transition disabled:opacity-50 disabled:cursor-not-allowed",
              confirmingDelete
                ? "bg-red-500 text-white hover:bg-red-600"
                : "border border-[#d0d0d0] text-red-500 hover:bg-red-50/60 hover:border-red-300",
            ].join(" ")}
          >
            {confirmingDelete ? "Click again to remove" : "Remove from graph"}
          </button>
          {confirmingDelete && (
            <div className="text-[10px] text-[#8a8a8a] mt-1.5 text-center leading-snug">
              {isSeed
                ? "Removes this seed and everything branching from it."
                : "Also removes any songs left disconnected from a seed."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] uppercase tracking-widest font-medium text-[#8a8a8a] mb-1">
      {children}
    </div>
  );
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  suffix,
  hint,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix: string;
  hint?: string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="mb-2">
      <div className="flex items-center justify-between mb-1">
        <Label>{label}</Label>
        <span className="font-mono text-xs tabular-nums text-[#3a3a3a]">{suffix}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-blue-500"
      />
      {hint && <div className="text-[10px] text-[#8a8a8a] mt-0.5">{hint}</div>}
    </div>
  );
}
